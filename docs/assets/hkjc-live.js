/* Browser live odds: HKJC GraphQL allows CORS *, so Pages can poll like the betting app. */
(function (global) {
  const GRAPHQL_URL = "https://info.cld.hkjc.com/graphql/base/";
  const QUERY_RACE_MEETINGS_FULL = "\n query raceMeetings($date: String, $venueCode: String) {\n timeOffset {\n rc\n }\n activeMeetings : raceMeetings\n {\n id\n venueCode\n date\n status\n races {\n no\n postTime\n status\n wageringFieldSize\n }\n poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {\n status\n }\n }\n raceMeetings(date: $date, venueCode: $venueCode)\n {\n id\n status\n venueCode\n date\n totalNumberOfRace\n currentNumberOfRace\n dateOfWeek\n meetingType\n totalInvestment\n country {\n code\n namech\n nameen\n seq\n }\n races {\n ...raceFragment\n runners {\n id\n no\n standbyNo\n status\n name_ch\n name_en\n horse {\n id\n code\n }\n color\n barrierDrawNumber\n handicapWeight\n currentWeight\n currentRating\n internationalRating\n gearInfo\n racingColorFileName\n allowance\n trainerPreference\n last6run\n saddleClothNo\n trumpCard\n priority\n finalPosition\n deadHeat\n winOdds\n jockey {\n code\n name_en\n name_ch\n }\n trainer {\n code\n name_en\n name_ch\n }\n }\n }\n obSt: pmPools(oddsTypes: [WIN, PLA]) {\n leg {\n races\n }\n oddsType\n comingleStatus\n }\n poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {\n id\n leg {\n number\n races\n }\n status\n sellStatus\n oddsType\n investment\n mergedPoolId\n lastUpdateTime\n }\n ...racingBlockFragment\n pmPools(oddsTypes: []) {\n id\n }\n jkcInstNo : foPools(oddsTypes: [JKC], filters: [\"top\"]) {\n instNo\n }\n tncInstNo : foPools(oddsTypes: [TNC], filters: [\"top\"]) {\n instNo\n }\n }\n }\n fragment raceFragment on Race {\n id\n no\n status\n raceName_en\n raceName_ch\n postTime\n country_en\n country_ch\n distance\n wageringFieldSize\n go_en\n go_ch\n ratingType\n raceTrack {\n description_en\n description_ch\n }\n raceCourse {\n description_en\n description_ch\n displayCode\n }\n claCode\n raceClass_en\n raceClass_ch\n judgeSigns {\n value_en\n }\n }fragment racingBlockFragment on RaceMeeting {\n jpEsts: pmPools(oddsTypes: [WIN,PLA,TCE,TRI,FF,QTT,DT,TT,SixUP], filters: [\"jackpot\", \"estimatedDividend\"]) {\n leg {\n number\n races\n }\n oddsType\n jackpot\n estimatedDividend\n mergedPoolId\n }\n poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {\n id\n leg {\n races\n }\n }\n penetrometerReadings(filters:[\"first\"]) {\n reading\n readingTime\n }\n hammerReadings(filters:[\"first\"]) {\n reading\n readingTime\n }\n changeHistories(filters:[\"top3\"]) {\n type\n time\n raceNo\n runnerNo\n horseName_ch\n horseName_en\n jockeyName_ch\n jockeyName_en\n scratchHorseName_ch\n scratchHorseName_en\n handicapWeight\n scrResvIndicator\n }\n }";
  const QUERY_PM_POOLS_ODDS = "\n query racing($date: String, $venueCode: String, $oddsTypes: [OddsType], $raceNo: Int) {\n raceMeetings(date: $date, venueCode: $venueCode)\n {\n pmPools(oddsTypes: $oddsTypes, raceNo: $raceNo) {\n id\n status\n sellStatus\n oddsType\n lastUpdateTime\n guarantee\n minTicketCost\n name_en\n name_ch\n leg {\n number\n races\n }\n cWinSelections {\n composite\n name_ch\n name_en\n starters\n }\n oddsNodes {\n combString\n oddsValue\n hotFavourite\n oddsDropValue\n bankerOdds {\n combString\n oddsValue\n }\n }\n }\n }\n }\n ";

  const meetingCache = { key: "", at: 0, value: null };
  const MEETING_TTL_MS = 20000;

  function parseOdds(value) {
    if (value == null) return null;
    const n = Number(String(value).replace(/,/g, ""));
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  function parseBrown(value) {
    const text = String(value == null ? "" : value).trim().toLowerCase();
    return text === "3" || text === "brown" || text === "coffee";
  }

  async function graphql(query, variables) {
    const res = await fetch(GRAPHQL_URL, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "Cache-Control": "no-cache",
      },
      body: JSON.stringify({ query, variables }),
    });
    if (!res.ok) throw new Error("HKJC GraphQL HTTP " + res.status);
    const payload = await res.json();
    if (payload && payload.errors && payload.errors.length) {
      throw new Error(payload.errors[0].message || "GraphQL error");
    }
    return payload && payload.data;
  }

  function pickMeetings(data) {
    const dated = data && data.raceMeetings;
    if (dated && dated.length) return dated;
    return (data && data.activeMeetings) || [];
  }

  async function fetchMeeting(date, venue, force) {
    const key = String(date || "") + "|" + String(venue || "").toUpperCase();
    if (!force && meetingCache.key === key && Date.now() - meetingCache.at < MEETING_TTL_MS) {
      return meetingCache.value;
    }
    const data = await graphql(QUERY_RACE_MEETINGS_FULL, { date: date, venueCode: venue });
    const meetings = pickMeetings(data);
    const wanted = String(venue || "").toUpperCase();
    const hit = meetings.find((m) => String(m.venueCode || "").toUpperCase() === wanted) || meetings[0];
    if (!hit) {
      meetingCache.key = key;
      meetingCache.at = Date.now();
      meetingCache.value = null;
      return null;
    }
    const races = (hit.races || []).map((race) => ({
      race_no: Number(race.no),
      post_time: race.postTime || "",
      status: String(race.status || ""),
      runners: (race.runners || []).filter((r) => !/scratch|standby/i.test(String(r.status || ""))).map((r) => ({
        horse_no: Number(r.no),
        horse_name: String(r.name_ch || r.name_en || "").trim(),
        status: String(r.status || ""),
      })),
    })).filter((r) => r.race_no > 0);
    races.sort((a, b) => a.race_no - b.race_no);
    const meeting = {
      race_date: String(hit.date || date).slice(0, 10),
      venue: String(hit.venueCode || venue).toUpperCase(),
      current_race: Number(hit.currentNumberOfRace || 0),
      status: String(hit.status || ""),
      races: races,
    };
    meetingCache.key = key;
    meetingCache.at = Date.now();
    meetingCache.value = meeting;
    return meeting;
  }

  function gridFromNode(node) {
    if (parseBrown(node && node.oddsDropValue)) return "brown";
    return "none";
  }

  async function fetchRaceOdds(date, venue, raceNo) {
    const data = await graphql(QUERY_PM_POOLS_ODDS, {
      date: date,
      venueCode: venue,
      oddsTypes: ["WIN", "PLA"],
      raceNo: raceNo,
    });
    const meetings = (data && data.raceMeetings) || [];
    const pools = (meetings[0] && meetings[0].pmPools) || [];
    const win = {};
    const pla = {};
    const winGrid = {};
    const plaGrid = {};
    pools.forEach((pool) => {
      const kind = String(pool.oddsType || "").toUpperCase();
      (pool.oddsNodes || []).forEach((node) => {
        const comb = String(node.combString || "").trim();
        if (!/^\d{1,2}$/.test(comb)) return;
        const n = Number(comb);
        const odds = parseOdds(node.oddsValue);
        const grid = gridFromNode(node);
        if (kind === "WIN") {
          win[n] = odds;
          winGrid[n] = grid;
        } else if (kind === "PLA") {
          pla[n] = odds;
          plaGrid[n] = grid;
        }
      });
    });
    return { win: win, pla: pla, winGrid: winGrid, plaGrid: plaGrid };
  }

  function racesToPoll(meeting) {
    if (!meeting || !meeting.races || !meeting.races.length) return [];
    const liveish = meeting.races.filter((r) => {
      const st = String(r.status || "").toLowerCase();
      return !/result|abandon|cancel|void|postpon/.test(st);
    });
    const cur = Number(meeting.current_race || 0);
    if (cur > 0) {
      return liveish.filter((r) => r.race_no >= cur && r.race_no <= cur + 1).slice(0, 2);
    }
    return liveish.slice(0, 2);
  }

  async function fetchLiveBoard(date, venue) {
    const meeting = await fetchMeeting(date, venue);
    if (!meeting) return { meeting: null, rows: [], error: "no meeting" };
    const targets = racesToPoll(meeting);
    const rows = [];
    for (const race of targets) {
      const odds = await fetchRaceOdds(meeting.race_date, meeting.venue, race.race_no);
      const names = {};
      (race.runners || []).forEach((r) => { names[r.horse_no] = r.horse_name; });
      const nos = new Set([].concat(Object.keys(odds.win), Object.keys(odds.pla), Object.keys(names)).map(Number));
      nos.forEach((n) => {
        if (!n) return;
        if (odds.win[n] == null && odds.pla[n] == null) return;
        rows.push({
          race_date: meeting.race_date,
          venue: meeting.venue,
          race_no: race.race_no,
          horse_no: n,
          horse_name: names[n] || "",
          win_odds: odds.win[n] == null ? "" : odds.win[n],
          place_odds: odds.pla[n] == null ? "" : odds.pla[n],
          hkjc_grid: odds.winGrid[n] || "none",
          place_grid: odds.plaGrid[n] || "none",
        });
      });
    }
    return { meeting: meeting, rows: rows, fetched_at: new Date().toISOString() };
  }

  global.HKJCLive = {
    fetchMeeting: fetchMeeting,
    fetchRaceOdds: fetchRaceOdds,
    fetchLiveBoard: fetchLiveBoard,
    parseBrown: parseBrown,
  };
})(window);

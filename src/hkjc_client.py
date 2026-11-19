"""Public HKJC racing data client (GraphQL whitelist + JSON/HTML fallbacks)."""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from bs4 import BeautifulSoup

from .logger import log, log_exception
from .odds_math import parse_odds
from .timeutil import combine_hk, parse_hk, today_hk, to_hk

GRAPHQL_URL = "https://info.cld.hkjc.com/graphql/base/"
JSON_ODDS_URL = "https://bet.hkjc.com/racing/getJSON.aspx"
RESULTS_URL = "https://racing.hkjc.com/racing/information/Chinese/Racing/LocalResults.aspx"
FIXTURE_URL = "https://racing.hkjc.com/racing/information/Chinese/Racing/Fixture.aspx"
LOCAL_VENUES = {"ST", "HV"}


def horse_name_zh(runner: dict | None, horse_no: int) -> str:
    data = runner or {}
    chinese = str(data.get("name_ch") or "").strip()
    if chinese:
        return chinese
    english = str(data.get("name_en") or "").strip()
    return english or f"第{horse_no}號"

# Verbatim whitelist queries used by bet.hkjc.com (modified queries return WHITELIST_ERROR).
QUERY_RACE_MEETINGS_FULL = """
 query raceMeetings($date: String, $venueCode: String) {
 timeOffset {
 rc
 }
 activeMeetings : raceMeetings
 {
 id
 venueCode
 date
 status
 races {
 no
 postTime
 status
 wageringFieldSize
 }
 poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {
 status
 }
 }
 raceMeetings(date: $date, venueCode: $venueCode)
 {
 id
 status
 venueCode
 date
 totalNumberOfRace
 currentNumberOfRace
 dateOfWeek
 meetingType
 totalInvestment
 country {
 code
 namech
 nameen
 seq
 }
 races {
 ...raceFragment
 runners {
 id
 no
 standbyNo
 status
 name_ch
 name_en
 horse {
 id
 code
 }
 color
 barrierDrawNumber
 handicapWeight
 currentWeight
 currentRating
 internationalRating
 gearInfo
 racingColorFileName
 allowance
 trainerPreference
 last6run
 saddleClothNo
 trumpCard
 priority
 finalPosition
 deadHeat
 winOdds
 jockey {
 code
 name_en
 name_ch
 }
 trainer {
 code
 name_en
 name_ch
 }
 }
 }
 obSt: pmPools(oddsTypes: [WIN, PLA]) {
 leg {
 races
 }
 oddsType
 comingleStatus
 }
 poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {
 id
 leg {
 number
 races
 }
 status
 sellStatus
 oddsType
 investment
 mergedPoolId
 lastUpdateTime
 }
 ...racingBlockFragment
 pmPools(oddsTypes: []) {
 id
 }
 jkcInstNo : foPools(oddsTypes: [JKC], filters: ["top"]) {
 instNo
 }
 tncInstNo : foPools(oddsTypes: [TNC], filters: ["top"]) {
 instNo
 }
 }
 }
 fragment raceFragment on Race {
 id
 no
 status
 raceName_en
 raceName_ch
 postTime
 country_en
 country_ch
 distance
 wageringFieldSize
 go_en
 go_ch
 ratingType
 raceTrack {
 description_en
 description_ch
 }
 raceCourse {
 description_en
 description_ch
 displayCode
 }
 claCode
 raceClass_en
 raceClass_ch
 judgeSigns {
 value_en
 }
 }fragment racingBlockFragment on RaceMeeting {
 jpEsts: pmPools(oddsTypes: [WIN,PLA,TCE,TRI,FF,QTT,DT,TT,SixUP], filters: ["jackpot", "estimatedDividend"]) {
 leg {
 number
 races
 }
 oddsType
 jackpot
 estimatedDividend
 mergedPoolId
 }
 poolInvs: pmPools(oddsTypes: [WIN,PLA,QIN,QPL,CWA,CWB,CWC,IWN,FCT,TCE,TRI,FF,QTT,DBL,TBL,DT,TT,SixUP]) {
 id
 leg {
 races
 }
 }
 penetrometerReadings(filters:["first"]) {
 reading
 readingTime
 }
 hammerReadings(filters:["first"]) {
 reading
 readingTime
 }
 changeHistories(filters:["top3"]) {
 type
 time
 raceNo
 runnerNo
 horseName_ch
 horseName_en
 jockeyName_ch
 jockeyName_en
 scratchHorseName_ch
 scratchHorseName_en
 handicapWeight
 scrResvIndicator
 }
 }"""

QUERY_PM_POOLS_ODDS = """
 query racing($date: String, $venueCode: String, $oddsTypes: [OddsType], $raceNo: Int) {
 raceMeetings(date: $date, venueCode: $venueCode)
 {
 pmPools(oddsTypes: $oddsTypes, raceNo: $raceNo) {
 id
 status
 sellStatus
 oddsType
 lastUpdateTime
 guarantee
 minTicketCost
 name_en
 name_ch
 leg {
 number
 races
 }
 cWinSelections {
 composite
 name_ch
 name_en
 starters
 }
 oddsNodes {
 combString
 oddsValue
 hotFavourite
 oddsDropValue
 bankerOdds {
 combString
 oddsValue
 }
 }
 }
 }
 }
 """

QUERY_RBC_LIST = """
 query rbcList($startDate: String, $endDate: String) {
 raceMeetings(startDate: $startDate, endDate: $endDate, all: true)
 {
 date
 venueCode
 }
 }
 """

QUERY_RESULT_MEETINGS = """
 query resultMeetings($date: String, $venueCode: String, $foOddsTypes: [OddsType], $foFilter: [String], $resultOddsType: [OddsType]) {
 raceMeetings(date: $date, venueCode: $venueCode)
 {
 id
 resPools: pmPools(oddsTypes: $resultOddsType) {
 leg {
 number
 races
 }
 status
 oddsType
 name_en
 name_ch
 lastUpdateTime
 dividends (officialOnly: true) {
 winComb
 type
 div
 seq
 status
 guarantee
 partial
 partialUnit
 }
 cWinSelections {
 composite
 name_ch
 name_en
 starters
 }
 }
 foPools(oddsTypes: $foOddsTypes, filters: $foFilter) {
 ...racingFoPoolFragment
 }
 }
 }
fragment racingFoPoolFragment on RacingFoPool {
 instNo
 poolId
 oddsType
 status
 sellStatus
 otherSelNo
 inplayUpTo
 expStartDateTime
 expStopDateTime
 raceStopSellNo
 raceStopSellStatus
 includeRaces
 excludeRaces
 lastUpdateTime
 selections {
 order
 number
 code
 name_en
 name_ch
 scheduleRides
 remainingRides
 points
 lineId
 combId
 combStatus
 openOdds
 prevOdds
 currentOdds
 results {
 raceNo
 points
 point1st
 point2nd
 point3rd
 dhRmk1st
 dhRmk2nd
 dhRmk3rd
 count1st
 count2nd
 count3rd
 count4th
 numerator4th
 denominator4th
 }
 }
 otherSelections {
 order
 code
 name_en
 name_ch
 scheduleRides
 remainingRides
 points
 results {
 raceNo
 points
 point1st
 point2nd
 point3rd
 dhRmk1st
 dhRmk2nd
 dhRmk3rd
 count1st
 count2nd
 count3rd
 count4th
 numerator4th
 denominator4th
 }
 }
 }"""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*, text/html",
    "Origin": "https://bet.hkjc.com",
    "Referer": "https://bet.hkjc.com/racing",
}


@dataclass
class RunnerOdds:
    horse_no: int
    horse_name: str
    win_odds: float | None
    place_odds: float | None
    status: str = "declared"


@dataclass
class RaceInfo:
    race_no: int
    post_time: str
    status: str = ""
    name: str = ""
    runners: dict[int, str] = field(default_factory=dict)
    runner_status: dict[int, str] = field(default_factory=dict)


@dataclass
class Meeting:
    race_date: str
    venue: str
    status: str = ""
    races: list[RaceInfo] = field(default_factory=list)

    def race(self, race_no: int) -> RaceInfo | None:
        for item in self.races:
            if item.race_no == race_no:
                return item
        return None


class HKJCClient:
    BLOCKED_STATUS = {403, 408, 429, 500, 502, 503, 504}

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.backoff_until = 0.0
        self.consecutive_blocks = 0

    def recommended_sleep(self, base_seconds: int) -> int:
        """Stretch the poll interval after 429/403 so we do not keep hammering HKJC."""
        extra = min(90, 15 * self.consecutive_blocks) if self.consecutive_blocks else 0
        wait = max(0.0, self.backoff_until - time.time())
        return int(max(base_seconds, wait, extra))

    def _request(self, method: str, url: str, **kwargs) -> requests.Response | None:
        retries = 5
        delay = 8.0
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if response.status_code in self.BLOCKED_STATUS:
                    retry_after = response.headers.get("Retry-After", "")
                    wait = float(retry_after) if str(retry_after).isdigit() else delay
                    wait = min(120.0, max(5.0, wait))
                    wait *= 0.85 + random.random() * 0.3
                    self.consecutive_blocks += 1
                    self.backoff_until = time.time() + wait
                    log(
                        f"HKJC HTTP {response.status_code} — backoff {wait:.0f}s "
                        f"(attempt {attempt}/{retries})",
                        level="WARN",
                    )
                    time.sleep(wait)
                    delay = min(120.0, delay * 2)
                    last_exc = RuntimeError(f"HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                self.consecutive_blocks = 0
                return response
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                wait = min(120.0, delay)
                self.consecutive_blocks += 1
                self.backoff_until = time.time() + wait
                log(f"HKJC network {type(exc).__name__} — backoff {wait:.0f}s", level="WARN")
                time.sleep(wait)
                delay = min(120.0, delay * 2)
        if last_exc:
            log_exception("HKJC request exhausted retries", last_exc)
        return None

    def _graphql(self, query: str, variables: dict | None = None) -> dict[str, Any] | None:
        response = self._request(
            "POST",
            GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers={"Content-Type": "application/json", **HEADERS},
        )
        if response is None:
            return None
        try:
            payload = response.json()
        except Exception as exc:
            log_exception("GraphQL JSON decode failed", exc)
            return None
        if payload.get("errors"):
            log(f"GraphQL errors: {payload['errors'][:2]}", level="WARN")
            return None
        return payload.get("data") or {}

    def list_local_meetings(self, start_date: str, end_date: str) -> list[tuple[str, str]]:
        data = self._graphql(QUERY_RBC_LIST, {"startDate": start_date, "endDate": end_date})
        meetings: list[tuple[str, str]] = []
        if data:
            for row in data.get("raceMeetings") or []:
                venue = (row.get("venueCode") or "").upper()
                date = (row.get("date") or "")[:10]
                if venue in LOCAL_VENUES and date:
                    meetings.append((date, venue))
        if meetings:
            return sorted(set(meetings))
        return self._fixture_meetings()

    def _fixture_meetings(self) -> list[tuple[str, str]]:
        response = self._request("GET", FIXTURE_URL)
        if response is None:
            return []
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        found: list[tuple[str, str]] = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            date_m = re.search(r"RaceDate=(\d{4}/\d{2}/\d{2})", href)
            venue_m = re.search(r"Racecourse=([A-Z]{2})", href)
            text = link.get_text(" ", strip=True).upper()
            venue = venue_m.group(1) if venue_m else ""
            if not venue:
                if "SHA TIN" in text or "沙田" in text:
                    venue = "ST"
                elif "HAPPY VALLEY" in text or "跑馬地" in text:
                    venue = "HV"
            if date_m and venue in LOCAL_VENUES:
                found.append((date_m.group(1).replace("/", "-"), venue))
        return sorted(set(found))

    def detect_today_meeting(self, race_date: str | None = None) -> Meeting | None:
        race_date = race_date or today_hk()
        for venue in ("ST", "HV"):
            meeting = self.fetch_meeting(race_date, venue)
            if meeting and meeting.races:
                log(f"Detected HK race day {race_date} {venue} ({len(meeting.races)} races)")
                return meeting
        log(f"No Hong Kong race meeting on {race_date}")
        return None

    def fetch_meeting(self, race_date: str, venue: str) -> Meeting | None:
        data = self._graphql(
            QUERY_RACE_MEETINGS_FULL,
            {"date": race_date, "venueCode": venue},
        )
        meetings = (data or {}).get("raceMeetings") or (data or {}).get("activeMeetings") or []
        for raw in meetings:
            code = (raw.get("venueCode") or venue).upper()
            date = (raw.get("date") or race_date)[:10]
            if code not in LOCAL_VENUES:
                continue
            if date and date != race_date:
                continue
            races: list[RaceInfo] = []
            for race in raw.get("races") or []:
                no = int(race.get("no") or 0)
                if no <= 0:
                    continue
                post = race.get("postTime") or ""
                try:
                    post_hk = to_hk(parse_hk(post)).strftime("%H:%M:%S") if post else ""
                except Exception:
                    post_hk = str(post)[11:19] if len(str(post)) >= 19 else str(post)
                runners = {}
                runner_status = {}
                for runner in race.get("runners") or []:
                    hno = int(runner.get("no") or 0)
                    if hno:
                        runners[hno] = horse_name_zh(runner, hno)
                        runner_status[hno] = str(runner.get("status") or "")
                races.append(
                    RaceInfo(
                        race_no=no,
                        post_time=post_hk,
                        status=str(race.get("status") or ""),
                        name=race.get("raceName_en") or race.get("raceName_ch") or "",
                        runners=runners,
                        runner_status=runner_status,
                    )
                )
            if races:
                races.sort(key=lambda r: r.race_no)
                return Meeting(
                    race_date=race_date,
                    venue=code,
                    status=str(raw.get("status") or ""),
                    races=races,
                )
        return self._meeting_from_results_page(race_date, venue)

    def _meeting_from_results_page(self, race_date: str, venue: str) -> Meeting | None:
        params = {
            "RaceDate": race_date.replace("-", "/"),
            "Racecourse": venue,
            "RaceNo": "1",
        }
        response = self._request("GET", RESULTS_URL, params=params)
        if response is None:
            return None
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        if venue == "ST" and "Sha Tin" not in text and "沙田" not in text:
            if "Happy Valley" in text or "跑馬地" in text:
                return None
        if venue == "HV" and "Happy Valley" not in text and "跑馬地" not in text:
            if "Sha Tin" in text or "沙田" in text:
                return None
        race_nos = []
        for option in soup.find_all("option"):
            try:
                value = int(option.get("value") or option.get_text(strip=True))
            except ValueError:
                continue
            if 1 <= value <= 14:
                race_nos.append(value)
        race_nos = sorted(set(race_nos)) or list(range(1, 11 if venue == "ST" else 9))
        races = [
            RaceInfo(race_no=n, post_time="", status="", name="", runners={})
            for n in race_nos
        ]
        if "No information" in text or "沒有資料" in text:
            return None
        if not race_nos:
            return None
        # Confirm the date actually appears
        compact = race_date.replace("-", "/")
        alt = f"{race_date[8:10]}/{race_date[5:7]}/{race_date[0:4]}"
        if compact not in text and alt not in text and race_date not in text:
            # still allow if venue name is present — some pages omit the ISO date
            if ("Sha Tin" not in text and "Happy Valley" not in text
                    and "沙田" not in text and "跑馬地" not in text):
                return None
        return Meeting(race_date=race_date, venue=venue, races=races)

    def fetch_win_place_odds(self, meeting: Meeting, race_no: int) -> list[RunnerOdds]:
        runners = self._odds_graphql(meeting, race_no)
        if runners:
            return runners
        return self._odds_json(meeting, race_no)

    def _odds_graphql(self, meeting: Meeting, race_no: int) -> list[RunnerOdds]:
        data = self._graphql(
            QUERY_PM_POOLS_ODDS,
            {
                "date": meeting.race_date,
                "venueCode": meeting.venue,
                "oddsTypes": ["WIN", "PLA"],
                "raceNo": race_no,
            },
        )
        meetings = (data or {}).get("raceMeetings") or []
        if not meetings:
            return []
        pools = meetings[0].get("pmPools") or []
        win_map: dict[int, float | None] = {}
        pla_map: dict[int, float | None] = {}
        for pool in pools:
            odds_type = str(pool.get("oddsType") or "").upper()
            if odds_type == "WIN":
                target = win_map
            elif odds_type == "PLA":
                target = pla_map
            else:
                continue
            for node in pool.get("oddsNodes") or []:
                comb = str(node.get("combString") or "").strip()
                if not re.fullmatch(r"\d{1,2}", comb):
                    continue
                target[int(comb)] = parse_odds(node.get("oddsValue"))
        if not win_map and not pla_map:
            return []
        race = meeting.race(race_no)
        names = race.runners if race else {}
        statuses = race.runner_status if race else {}
        numbers = sorted(set(win_map) | set(pla_map) | set(names))
        return [
            RunnerOdds(
                horse_no=n,
                horse_name=names.get(n) or f"第{n}號",
                win_odds=win_map.get(n),
                place_odds=pla_map.get(n),
                status=statuses.get(n) or "declared",
            )
            for n in numbers
        ]

    def _odds_json(self, meeting: Meeting, race_no: int) -> list[RunnerOdds]:
        params = {
            "type": "winplaodds",
            "date": meeting.race_date,
            "venue": meeting.venue,
            "start": race_no,
            "end": race_no,
        }
        response = self._request("GET", JSON_ODDS_URL, params=params)
        if response is None:
            return []
        try:
            payload = response.json()
        except Exception as exc:
            log_exception("getJSON winplaodds JSON decode failed", exc)
            return []
        raw = payload.get("OUT") if isinstance(payload, dict) else str(payload)
        if not raw or "WIN" not in str(raw):
            return []
        win_map: dict[int, float | None] = {}
        pla_map: dict[int, float | None] = {}
        text = str(raw)
        win_part, _, pla_part = text.partition("#")
        self._parse_pool_segment(win_part, win_map)
        self._parse_pool_segment(pla_part, pla_map)
        race = meeting.race(race_no)
        names = race.runners if race else {}
        statuses = race.runner_status if race else {}
        numbers = sorted(set(win_map) | set(pla_map) | set(names))
        return [
            RunnerOdds(
                horse_no=n,
                horse_name=names.get(n) or f"第{n}號",
                win_odds=win_map.get(n),
                place_odds=pla_map.get(n),
                status=statuses.get(n) or "declared",
            )
            for n in numbers
        ]

    @staticmethod
    def _parse_pool_segment(segment: str, target: dict[int, float | None]) -> None:
        # WIN;1=3.5=0;2=12=1  or  1=3.5=0;2=12=1
        body = segment.split(";", 1)[-1] if ";" in segment else segment
        for token in body.split(";"):
            parts = token.split("=")
            if len(parts) < 2:
                continue
            try:
                horse_no = int(parts[0])
            except ValueError:
                continue
            target[horse_no] = parse_odds(parts[1])

    def fetch_results(self, meeting: Meeting, race_no: int) -> list[dict]:
        rows = self._results_html(meeting, race_no)
        if rows:
            return rows
        return self._results_graphql(meeting, race_no)

    def _results_graphql(self, meeting: Meeting, race_no: int) -> list[dict]:
        data = self._graphql(
            QUERY_RESULT_MEETINGS,
            {
                "date": meeting.race_date,
                "venueCode": meeting.venue,
                "foOddsTypes": ["JKC"],
                "foFilter": ["top"],
                "resultOddsType": ["WIN", "PLA"],
            },
        )
        meetings = (data or {}).get("raceMeetings") or []
        if not meetings:
            return []
        race = meeting.race(race_no)
        names = race.runners if race else {}
        win_div: dict[int, float] = {}
        pla_div: dict[int, float] = {}
        for pool in meetings[0].get("resPools") or []:
            legs = pool.get("leg") or []
            race_list = []
            for leg in legs:
                race_list.extend(leg.get("races") or [])
            if race_list and race_no not in race_list:
                continue
            dest = win_div if pool.get("oddsType") == "WIN" else pla_div
            for item in pool.get("dividends") or []:
                comb = str(item.get("winComb") or "").strip()
                if not re.fullmatch(r"\d{1,2}", comb):
                    continue
                dest[int(comb)] = float(parse_odds(item.get("div")) or 0)
        if not win_div and not pla_div:
            return []
        numbers = sorted(set(names) | set(win_div) | set(pla_div))
        out = []
        for n in numbers:
            out.append(
                {
                    "race_date": meeting.race_date,
                    "venue": meeting.venue,
                    "race_no": race_no,
                    "horse_no": n,
                    "horse_name": names.get(n) or f"第{n}號",
                    "finish_rank": "",
                    "final_sp": "",
                    "win_dividend": win_div.get(n, 0) or 0,
                    "placedividend": pla_div.get(n, 0) or 0,
                }
            )
        return out

    def _results_html(self, meeting: Meeting, race_no: int) -> list[dict]:
        params = {
            "RaceDate": meeting.race_date.replace("-", "/"),
            "Racecourse": meeting.venue,
            "RaceNo": str(race_no),
        }
        response = self._request("GET", RESULTS_URL, params=params)
        if response is None:
            return []
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        performance = self._find_table(soup, ["名次", "馬號", "馬名"])
        if performance is None:
            performance = self._find_table(soup, ["Pla", "Horse No", "Horse", "Win Odds"])
        if performance is None:
            return []
        rows_out: list[dict] = []
        header_cells = performance.find_all("tr")[0].find_all(["td", "th"])
        header_names = [c.get_text(" ", strip=True) for c in header_cells]
        header_lower = [h.lower() for h in header_names]

        def col(*names: str) -> int | None:
            def compact(value: str) -> str:
                return re.sub(r"\s+", "", value or "").lower()

            wanted = [compact(name) for name in names if name]
            for i, h in enumerate(header_names):
                hc = compact(h)
                if any(token and token in hc for token in wanted):
                    return i
            for i, h in enumerate(header_lower):
                hc = compact(h)
                if any(token and token in hc for token in wanted):
                    return i
            return None

        idx_pla = col("名次", "pla.")
        idx_no = col("馬號", "horse no")
        idx_name = col("馬名")
        if idx_name is None:
            for i, h in enumerate(header_lower):
                if h.strip() in {"horse", "horse name"}:
                    idx_name = i
                    break
        idx_odds = col("獨贏賠率", "win odds")
        for tr in performance.find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            horse_no = self._to_int(cells[idx_no] if idx_no is not None else "")
            if not horse_no:
                continue
            rank_raw = cells[idx_pla] if idx_pla is not None else ""
            rank = self._to_int(re.sub(r"[^0-9]", "", rank_raw.split()[0] if rank_raw else ""))
            name = cells[idx_name] if idx_name is not None else f"第{horse_no}號"
            name = re.sub(r"\s*\([A-Z]\d+\)\s*$", "", name).strip() or f"第{horse_no}號"
            sp = parse_odds(cells[idx_odds] if idx_odds is not None else None)
            rows_out.append(
                {
                    "race_date": meeting.race_date,
                    "venue": meeting.venue,
                    "race_no": race_no,
                    "horse_no": horse_no,
                    "horse_name": name,
                    "finish_rank": rank or "",
                    "final_sp": sp if sp is not None else "",
                    "win_dividend": 0,
                    "placedividend": 0,
                }
            )

        win_div, pla_div = self._parse_dividend_table(soup)
        for row in rows_out:
            n = int(row["horse_no"])
            row["win_dividend"] = win_div.get(n, 0)
            row["placedividend"] = pla_div.get(n, 0)
        return rows_out

    @staticmethod
    def _find_table(soup: BeautifulSoup, must_have: list[str]):
        for table in soup.find_all("table"):
            text = table.get_text(" ", strip=True)
            if all(token in text for token in must_have):
                return table
        return None

    @staticmethod
    def _to_int(value: str) -> int:
        try:
            return int(re.sub(r"[^0-9]", "", str(value)) or 0)
        except ValueError:
            return 0

    def _parse_dividend_table(self, soup: BeautifulSoup) -> tuple[dict[int, float], dict[int, float]]:
        win_div: dict[int, float] = {}
        pla_div: dict[int, float] = {}
        table = None
        for candidate in soup.find_all("table"):
            text = candidate.get_text(" ", strip=True).upper()
            if "DIVIDEND" in text or "派彩" in text:
                table = candidate
                break
        if table is None:
            return win_div, pla_div
        current_pool = ""
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if not cells:
                continue
            label = re.sub(r"\s+", "", cells[0] or "")
            upper = label.upper()
            if label in {"獨贏"} or upper == "WIN":
                current_pool = "WIN"
            elif label in {"位置"} or upper == "PLACE":
                current_pool = "PLA"
            elif label:
                # 位置Q / 連贏 / 二重彩… must not reuse 位置 horse numbers
                current_pool = ""
            numbers = [int(x) for x in re.findall(r"\b(\d{1,2})\b", " ".join(cells))]
            money = re.findall(r"\$?\s*([0-9]+\.[0-9]+)", " ".join(cells))
            if current_pool == "WIN" and numbers and money:
                win_div[numbers[0]] = float(money[0])
            elif current_pool == "PLA":
                n = self._to_int(cells[1] if len(cells) > 1 else cells[0])
                divs = re.findall(r"([0-9]+\.[0-9]+)", cells[-1] if cells else "")
                if n and divs:
                    pla_div[n] = float(divs[0])
                elif numbers and money:
                    for horse_no, amount in zip(numbers, money):
                        pla_div[horse_no] = float(amount)
        return win_div, pla_div

    @staticmethod
    def scheduled_datetime(meeting: Meeting, race: RaceInfo):
        if not race.post_time:
            return None
        try:
            return combine_hk(meeting.race_date, race.post_time)
        except Exception:
            return None

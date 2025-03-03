import json
from datetime import datetime
from typing import List

from freezegun import freeze_time

from posthog.constants import TRENDS_LIFECYCLE, TRENDS_TABLE
from posthog.models import Action, ActionStep, Cohort, Event, Filter, Organization, Person
from posthog.queries.abstract_test.test_interval import AbstractIntervalTest
from posthog.queries.abstract_test.test_timerange import AbstractTimerangeTest
from posthog.queries.trends import Trends
from posthog.tasks.calculate_action import calculate_action, calculate_actions_from_last_calculation
from posthog.test.base import APIBaseTest
from posthog.utils import generate_cache_key, relative_date_parse


# parameterize tests to reuse in EE
def trend_test_factory(trends, event_factory, person_factory, action_factory, cohort_factory):
    class TestTrends(AbstractTimerangeTest, AbstractIntervalTest, APIBaseTest):
        def _create_events(self, use_time=False):

            person = person_factory(
                team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
            )
            _, _, secondTeam = Organization.objects.bootstrap(None, team_fields={"api_token": "token456"})

            freeze_without_time = ["2019-12-24", "2020-01-01", "2020-01-02"]
            freeze_with_time = [
                "2019-12-24 03:45:34",
                "2020-01-01 00:06:34",
                "2020-01-02 16:34:34",
            ]

            freeze_args = freeze_without_time
            if use_time:
                freeze_args = freeze_with_time

            with freeze_time(freeze_args[0]):
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": "value"},
                )

            with freeze_time(freeze_args[1]):
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": "value"},
                )
                event_factory(team=self.team, event="sign up", distinct_id="anonymous_id")
                event_factory(team=self.team, event="sign up", distinct_id="blabla")
            with freeze_time(freeze_args[2]):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "other_value", "$some_numerical_prop": 80,},
                )
                event_factory(team=self.team, event="no events", distinct_id="blabla")

                # second team should have no effect
                event_factory(
                    team=secondTeam,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "other_value"},
                )

            no_events = action_factory(team=self.team, name="no events")
            sign_up_action = action_factory(team=self.team, name="sign up")

            calculate_actions_from_last_calculation()

            return sign_up_action, person

        def _create_breakdown_events(self):
            freeze_without_time = ["2020-01-02"]

            with freeze_time(freeze_without_time[0]):
                for i in range(25):
                    event_factory(
                        team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": i},
                    )
            sign_up_action = action_factory(team=self.team, name="sign up")

        def assertEntityResponseEqual(self, response1, response2, remove=("action", "label")):
            if len(response1):
                for attr in remove:
                    response1[0].pop(attr)
            else:
                return False
            if len(response2):
                for attr in remove:
                    response2[0].pop(attr)
            else:
                return False
            self.assertDictEqual(response1[0], response2[0])

        def test_trends_per_day(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                # with self.assertNumQueries(16):
                response = trends().run(
                    Filter(data={"date_from": "-7d", "events": [{"id": "sign up"}, {"id": "no events"}],}), self.team,
                )
            self.assertEqual(response[0]["label"], "sign up")
            self.assertEqual(response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(response[0]["data"][4], 3.0)
            self.assertEqual(response[0]["labels"][5], "Thu. 2 January")
            self.assertEqual(response[0]["data"][5], 1.0)

        # just make sure this doesn't error
        def test_no_props(self):
            with freeze_time("2020-01-04T13:01:01Z"):
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$some_property",
                            "events": [
                                {"id": "sign up", "name": "sign up", "type": "events", "order": 0,},
                                {"id": "no events"},
                            ],
                        }
                    ),
                    self.team,
                )

        def test_trends_per_day_48hours(self):
            self._create_events()
            with freeze_time("2020-01-03T13:00:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-48h",
                            "interval": "day",
                            "events": [{"id": "sign up"}, {"id": "no events"}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["data"][1], 1.0)
            self.assertEqual(response[0]["labels"][1], "Thu. 2 January")

        def test_trends_per_day_cumulative(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):

                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-7d",
                            "display": "ActionsLineGraphCumulative",
                            "events": [{"id": "sign up"}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["label"], "sign up")
            self.assertEqual(response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(response[0]["data"][4], 3.0)
            self.assertEqual(response[0]["labels"][5], "Thu. 2 January")
            self.assertEqual(response[0]["data"][5], 4.0)

        def test_trends_single_aggregate_dau(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "week",
                            "events": [{"id": "sign up", "math": "dau"}],
                        }
                    ),
                    self.team,
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                weekly_response = trends().run(
                    Filter(
                        data={"display": TRENDS_TABLE, "interval": "day", "events": [{"id": "sign up", "math": "dau"}],}
                    ),
                    self.team,
                )

            self.assertEqual(daily_response[0]["aggregated_value"], 1)
            self.assertEqual(daily_response[0]["aggregated_value"], weekly_response[0]["aggregated_value"])

        def test_trends_single_aggregate_math(self):
            person = person_factory(
                team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
            )
            with freeze_time("2020-01-01 00:06:34"):
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 1},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 1},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 1},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 2},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 3},
                )

            with freeze_time("2020-01-02 00:06:34"):
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 4},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 4},
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "week",
                            "events": [{"id": "sign up", "math": "median", "math_property": "$math_prop"}],
                        }
                    ),
                    self.team,
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                weekly_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "day",
                            "events": [{"id": "sign up", "math": "median", "math_property": "$math_prop"}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(daily_response[0]["aggregated_value"], 2.0)
            self.assertEqual(daily_response[0]["aggregated_value"], weekly_response[0]["aggregated_value"])

        def test_trends_breakdown_single_aggregate_cohorts(self):
            person_1 = person_factory(team_id=self.team.pk, distinct_ids=["Jane"], properties={"name": "Jane"})
            person_2 = person_factory(team_id=self.team.pk, distinct_ids=["John"], properties={"name": "John"})
            person_3 = person_factory(team_id=self.team.pk, distinct_ids=["Jill"], properties={"name": "Jill"})
            cohort1 = cohort_factory(team=self.team, name="cohort1", groups=[{"properties": {"name": "Jane"}}])
            cohort2 = cohort_factory(team=self.team, name="cohort2", groups=[{"properties": {"name": "John"}}])
            cohort3 = cohort_factory(team=self.team, name="cohort3", groups=[{"properties": {"name": "Jill"}}])
            with freeze_time("2020-01-01 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="John",
                    properties={"$some_property": "value", "$browser": "Chrome"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="John",
                    properties={"$some_property": "value", "$browser": "Chrome"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jill",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jill",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jill",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )

            with freeze_time("2020-01-02 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jane",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jane",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
            with freeze_time("2020-01-04T13:00:01Z"):
                event_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "breakdown": json.dumps([cohort1.pk, cohort2.pk, cohort3.pk, "all"]),
                            "breakdown_type": "cohort",
                            "events": [{"id": "sign up"}],
                        }
                    ),
                    self.team,
                )

            for result in event_response:
                if result["label"] == "sign up - cohort1":
                    self.assertEqual(result["aggregated_value"], 2)
                elif result["label"] == "sign up - cohort2":
                    self.assertEqual(result["aggregated_value"], 2)
                elif result["label"] == "sign up - cohort3":
                    self.assertEqual(result["aggregated_value"], 3)
                else:
                    self.assertEqual(result["aggregated_value"], 7)

        def test_trends_breakdown_single_aggregate(self):
            person = person_factory(
                team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
            )
            with freeze_time("2020-01-01 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Chrome"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Chrome"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )

            with freeze_time("2020-01-02 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = trends().run(
                    Filter(data={"display": TRENDS_TABLE, "breakdown": "$browser", "events": [{"id": "sign up"}],}),
                    self.team,
                )

            for result in daily_response:
                if result["breakdown_value"] == "Chrome":
                    self.assertEqual(result["aggregated_value"], 2)
                else:
                    self.assertEqual(result["aggregated_value"], 5)

        def test_trends_breakdown_single_aggregate_math(self):
            person = person_factory(
                team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
            )
            with freeze_time("2020-01-01 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 1},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 1},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 1},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 2},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 3},
                )

            with freeze_time("2020-01-02 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 4},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 4},
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "week",
                            "breakdown": "$some_property",
                            "events": [{"id": "sign up", "math": "median", "math_property": "$math_prop"}],
                        }
                    ),
                    self.team,
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                weekly_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "day",
                            "breakdown": "$some_property",
                            "events": [{"id": "sign up", "math": "median", "math_property": "$math_prop"}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(daily_response[0]["aggregated_value"], 2.0)
            self.assertEqual(daily_response[0]["aggregated_value"], weekly_response[0]["aggregated_value"])

        def test_trends_compare(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                response = trends().run(Filter(data={"compare": "true", "events": [{"id": "sign up"}]}), self.team)

            self.assertEqual(response[0]["label"], "sign up - current")
            self.assertEqual(response[0]["labels"][4], "day 4")
            self.assertEqual(response[0]["data"][4], 3.0)
            self.assertEqual(response[0]["labels"][5], "day 5")
            self.assertEqual(response[0]["data"][5], 1.0)

            self.assertEqual(response[1]["label"], "sign up - previous")
            self.assertEqual(response[1]["labels"][4], "day 4")
            self.assertEqual(response[1]["data"][4], 1.0)
            self.assertEqual(response[1]["labels"][5], "day 5")
            self.assertEqual(response[1]["data"][5], 0.0)

            with freeze_time("2020-01-04T13:00:01Z"):
                no_compare_response = trends().run(
                    Filter(data={"compare": "false", "events": [{"id": "sign up"}]}), self.team
                )

            self.assertEqual(no_compare_response[0]["label"], "sign up")
            self.assertEqual(no_compare_response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(no_compare_response[0]["data"][4], 3.0)
            self.assertEqual(no_compare_response[0]["labels"][5], "Thu. 2 January")
            self.assertEqual(no_compare_response[0]["data"][5], 1.0)

        def _test_events_with_dates(self, dates: List[str], result, query_time=None, **filter_params):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
            for time in dates:
                with freeze_time(time):
                    event_factory(
                        event="event_name", team=self.team, distinct_id="person_1", properties={"$browser": "Safari"},
                    )

            if query_time:
                with freeze_time(query_time):
                    response = trends().run(
                        Filter(data={**filter_params, "events": [{"id": "event_name"}]}), self.team,
                    )
            else:
                response = trends().run(Filter(data={**filter_params, "events": [{"id": "event_name"}]}), self.team,)
            self.assertEqual(response, result)

        def test_minute_interval(self):
            self._test_events_with_dates(
                dates=["2020-11-01 10:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00"],
                interval="minute",
                date_from="2020-11-01 10:20:00",
                date_to="2020-11-01 10:30:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                        "labels": [
                            "Sun. 1 November, 10:20",
                            "Sun. 1 November, 10:21",
                            "Sun. 1 November, 10:22",
                            "Sun. 1 November, 10:23",
                            "Sun. 1 November, 10:24",
                            "Sun. 1 November, 10:25",
                            "Sun. 1 November, 10:26",
                            "Sun. 1 November, 10:27",
                            "Sun. 1 November, 10:28",
                            "Sun. 1 November, 10:29",
                            "Sun. 1 November, 10:30",
                        ],
                        "days": [
                            "2020-11-01 10:20:00",
                            "2020-11-01 10:21:00",
                            "2020-11-01 10:22:00",
                            "2020-11-01 10:23:00",
                            "2020-11-01 10:24:00",
                            "2020-11-01 10:25:00",
                            "2020-11-01 10:26:00",
                            "2020-11-01 10:27:00",
                            "2020-11-01 10:28:00",
                            "2020-11-01 10:29:00",
                            "2020-11-01 10:30:00",
                        ],
                    }
                ],
            )

        def test_hour_interval(self):
            self._test_events_with_dates(
                dates=["2020-11-01 13:00:00", "2020-11-01 13:20:00", "2020-11-01 17:00:00"],
                interval="hour",
                date_from="2020-11-01 12:00:00",
                date_to="2020-11-01 18:00:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [0.0, 2.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                        "labels": [
                            "Sun. 1 November, 12:00",
                            "Sun. 1 November, 13:00",
                            "Sun. 1 November, 14:00",
                            "Sun. 1 November, 15:00",
                            "Sun. 1 November, 16:00",
                            "Sun. 1 November, 17:00",
                            "Sun. 1 November, 18:00",
                        ],
                        "days": [
                            "2020-11-01 12:00:00",
                            "2020-11-01 13:00:00",
                            "2020-11-01 14:00:00",
                            "2020-11-01 15:00:00",
                            "2020-11-01 16:00:00",
                            "2020-11-01 17:00:00",
                            "2020-11-01 18:00:00",
                        ],
                    }
                ],
            )

        def test_day_interval(self):
            self._test_events_with_dates(
                dates=["2020-11-01", "2020-11-02", "2020-11-03", "2020-11-04"],
                interval="day",
                date_from="2020-11-01",
                date_to="2020-11-07",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
                        "labels": [
                            "Sun. 1 November",
                            "Mon. 2 November",
                            "Tue. 3 November",
                            "Wed. 4 November",
                            "Thu. 5 November",
                            "Fri. 6 November",
                            "Sat. 7 November",
                        ],
                        "days": [
                            "2020-11-01",
                            "2020-11-02",
                            "2020-11-03",
                            "2020-11-04",
                            "2020-11-05",
                            "2020-11-06",
                            "2020-11-07",
                        ],
                    }
                ],
            )

        def test_week_interval(self):
            self._test_events_with_dates(
                dates=["2020-11-01", "2020-11-10", "2020-11-11", "2020-11-18"],
                interval="week",
                date_from="2020-11-01",
                date_to="2020-11-24",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [1.0, 2.0, 1.0, 0.0],
                        "labels": ["Sun. 1 November", "Sun. 8 November", "Sun. 15 November", "Sun. 22 November"],
                        "days": ["2020-11-01", "2020-11-08", "2020-11-15", "2020-11-22"],
                    }
                ],
            )

        def test_month_interval(self):
            self._test_events_with_dates(
                dates=["2020-06-01", "2020-07-10", "2020-07-30", "2020-10-18"],
                interval="month",
                date_from="2020-6-01",
                date_to="2020-11-24",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [1.0, 2.0, 0.0, 0.0, 1.0, 0.0],
                        "labels": [
                            "Mon. 1 June",
                            "Wed. 1 July",
                            "Sat. 1 August",
                            "Tue. 1 September",
                            "Thu. 1 October",
                            "Sun. 1 November",
                        ],
                        "days": ["2020-06-01", "2020-07-01", "2020-08-01", "2020-09-01", "2020-10-01", "2020-11-01"],
                    }
                ],
            )

        def test_interval_rounding(self):
            self._test_events_with_dates(
                dates=["2020-11-01", "2020-11-10", "2020-11-11", "2020-11-18"],
                interval="week",
                date_from="2020-11-04",
                date_to="2020-11-24",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [2.0, 1.0, 0.0],
                        "labels": ["Sun. 8 November", "Sun. 15 November", "Sun. 22 November"],
                        "days": ["2020-11-08", "2020-11-15", "2020-11-22"],
                    }
                ],
            )

        def test_today_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 10:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00"],
                date_from="dStart",
                query_time="2020-11-01 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3,
                        "data": [3],
                        "labels": ["Sun. 1 November"],
                        "days": ["2020-11-01"],
                    }
                ],
            )

        def test_yesterday_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 05:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00"],
                date_from="-1d",
                date_to="dStart",
                query_time="2020-11-02 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [3.0, 0.0],
                        "labels": ["Sun. 1 November", "Mon. 2 November"],
                        "days": ["2020-11-01", "2020-11-02"],
                    }
                ],
            )

        def test_last24hours_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 05:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00", "2020-11-02 08:25:00"],
                date_from="-24h",
                query_time="2020-11-02 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3,
                        "data": [2, 1],
                        "labels": ["Sun. 1 November", "Mon. 2 November"],
                        "days": ["2020-11-01", "2020-11-02"],
                    }
                ],
            )

        def test_last48hours_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 05:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00", "2020-11-02 08:25:00"],
                date_from="-48h",
                query_time="2020-11-02 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [0.0, 3.0, 1.0],
                        "labels": ["Sat. 31 October", "Sun. 1 November", "Mon. 2 November"],
                        "days": ["2020-10-31", "2020-11-01", "2020-11-02"],
                    }
                ],
            )

        def test_last7days_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 05:20:00", "2020-11-02 10:22:00", "2020-11-04 10:25:00", "2020-11-05 08:25:00"],
                date_from="-7d",
                query_time="2020-11-07 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0],
                        "labels": [
                            "Sat. 31 October",
                            "Sun. 1 November",
                            "Mon. 2 November",
                            "Tue. 3 November",
                            "Wed. 4 November",
                            "Thu. 5 November",
                            "Fri. 6 November",
                            "Sat. 7 November",
                        ],
                        "days": [
                            "2020-10-31",
                            "2020-11-01",
                            "2020-11-02",
                            "2020-11-03",
                            "2020-11-04",
                            "2020-11-05",
                            "2020-11-06",
                            "2020-11-07",
                        ],
                    }
                ],
            )

        def test_last14days_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-11-01 05:20:00",
                    "2020-11-02 10:22:00",
                    "2020-11-04 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="-14d",
                query_time="2020-11-14 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 6.0,
                        "data": [0.0, 1.0, 1.0, 0.0, 1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
                        "labels": [
                            "Sat. 31 October",
                            "Sun. 1 November",
                            "Mon. 2 November",
                            "Tue. 3 November",
                            "Wed. 4 November",
                            "Thu. 5 November",
                            "Fri. 6 November",
                            "Sat. 7 November",
                            "Sun. 8 November",
                            "Mon. 9 November",
                            "Tue. 10 November",
                            "Wed. 11 November",
                            "Thu. 12 November",
                            "Fri. 13 November",
                            "Sat. 14 November",
                        ],
                        "days": [
                            "2020-10-31",
                            "2020-11-01",
                            "2020-11-02",
                            "2020-11-03",
                            "2020-11-04",
                            "2020-11-05",
                            "2020-11-06",
                            "2020-11-07",
                            "2020-11-08",
                            "2020-11-09",
                            "2020-11-10",
                            "2020-11-11",
                            "2020-11-12",
                            "2020-11-13",
                            "2020-11-14",
                        ],
                    }
                ],
            )

        def test_last30days_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-11-01 05:20:00",
                    "2020-11-11 10:22:00",
                    "2020-11-24 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="-30d",
                interval="week",
                query_time="2020-11-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 6.0,
                        "data": [3.0, 2.0, 0.0, 1.0, 0.0],
                        "labels": [
                            "Sun. 1 November",
                            "Sun. 8 November",
                            "Sun. 15 November",
                            "Sun. 22 November",
                            "Sun. 29 November",
                        ],
                        "days": ["2020-11-01", "2020-11-08", "2020-11-15", "2020-11-22", "2020-11-29"],
                    }
                ],
            )

        def test_last90days_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-09-01 05:20:00",
                    "2020-10-05 05:20:00",
                    "2020-10-20 05:20:00",
                    "2020-11-01 05:20:00",
                    "2020-11-11 10:22:00",
                    "2020-11-24 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="-90d",
                interval="month",
                query_time="2020-11-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 9,
                        "data": [1, 2, 6],
                        "labels": ["Tue. 1 September", "Thu. 1 October", "Sun. 1 November"],
                        "days": ["2020-09-01", "2020-10-01", "2020-11-01"],
                    }
                ],
            )

        def test_this_month_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-11-01 05:20:00",
                    "2020-11-11 10:22:00",
                    "2020-11-24 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="mStart",
                interval="month",
                query_time="2020-11-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 6,
                        "data": [6],
                        "labels": ["Sun. 1 November"],
                        "days": ["2020-11-01"],
                    }
                ],
            )

        def test_previous_month_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-11-01 05:20:00",
                    "2020-11-11 10:22:00",
                    "2020-11-24 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="-1mStart",
                date_to="-1mEnd",
                interval="month",
                query_time="2020-12-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 6,
                        "data": [6],
                        "labels": ["Sun. 1 November"],
                        "days": ["2020-11-01"],
                    }
                ],
            )

        def test_year_to_date_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-01-01 05:20:00",
                    "2020-01-11 10:22:00",
                    "2020-02-24 10:25:00",
                    "2020-02-05 08:25:00",
                    "2020-03-05 08:25:00",
                    "2020-05-10 08:25:00",
                ],
                date_from="yStart",
                interval="month",
                query_time="2020-04-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 5.0,
                        "data": [2.0, 2.0, 1.0, 0.0],
                        "labels": ["Wed. 1 January", "Sat. 1 February", "Sun. 1 March", "Wed. 1 April"],
                        "days": ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"],
                    }
                ],
            )

        def test_all_time_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-01-01 05:20:00",
                    "2020-01-11 10:22:00",
                    "2020-02-24 10:25:00",
                    "2020-02-05 08:25:00",
                    "2020-03-05 08:25:00",
                ],
                date_from="all",
                interval="month",
                query_time="2020-04-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 5.0,
                        "data": [2.0, 2.0, 1.0, 0.0],
                        "labels": ["Wed. 1 January", "Sat. 1 February", "Sun. 1 March", "Wed. 1 April"],
                        "days": ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"],
                    }
                ],
            )

        def test_custom_range_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-01-05 05:20:00",
                    "2020-01-05 10:22:00",
                    "2020-01-04 10:25:00",
                    "2020-01-11 08:25:00",
                    "2020-01-09 08:25:00",
                ],
                date_from="2020-01-05",
                query_time="2020-01-10",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [2.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                        "labels": [
                            "Sun. 5 January",
                            "Mon. 6 January",
                            "Tue. 7 January",
                            "Wed. 8 January",
                            "Thu. 9 January",
                            "Fri. 10 January",
                        ],
                        "days": ["2020-01-05", "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10"],
                    }
                ],
            )

        def test_property_filtering(self):
            self._create_events()
            with freeze_time("2020-01-04"):
                response = trends().run(
                    Filter(
                        data={
                            "properties": [{"key": "$some_property", "value": "value"}],
                            "events": [{"id": "sign up"}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(response[0]["data"][4], 1.0)
            self.assertEqual(response[0]["labels"][5], "Thu. 2 January")
            self.assertEqual(response[0]["data"][5], 0)

        def test_filter_events_by_cohort(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

            event1 = event_factory(
                event="event_name", team=self.team, distinct_id="person_1", properties={"$browser": "Safari"},
            )
            event2 = event_factory(
                event="event_name", team=self.team, distinct_id="person_2", properties={"$browser": "Chrome"},
            )
            event3 = event_factory(
                event="event_name", team=self.team, distinct_id="person_2", properties={"$browser": "Safari"},
            )

            cohort = cohort_factory(team=self.team, name="cohort1", groups=[{"properties": {"name": "Jane"}}])

            response = trends().run(
                Filter(
                    data={
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "events": [{"id": "event_name"}],
                    }
                ),
                self.team,
            )

            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[0]["data"][-1], 2)

        def test_response_empty_if_no_events(self):
            self._create_events()
            response = trends().run(Filter(data={"date_from": "2012-12-12"}), self.team)
            self.assertEqual(response, [])

        def test_interval_filtering(self):
            self._create_events(use_time=True)

            # test minute
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2020-01-01", "interval": "minute", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][6], "Wed. 1 January, 00:06")
            self.assertEqual(response[0]["data"][6], 3.0)

            # test hour
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2019-12-24", "interval": "hour", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][3], "Tue. 24 December, 03:00")
            self.assertEqual(response[0]["data"][3], 1.0)
            # 217 - 24 - 1
            self.assertEqual(response[0]["data"][192], 3.0)

            # test week
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2019-11-24", "interval": "week", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][4], "Sun. 22 December")
            self.assertEqual(response[0]["data"][4], 1.0)
            self.assertEqual(response[0]["labels"][5], "Sun. 29 December")
            self.assertEqual(response[0]["data"][5], 4.0)

            # test month
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2019-9-24", "interval": "month", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][2], "Sun. 1 December")
            self.assertEqual(response[0]["data"][2], 1.0)
            self.assertEqual(response[0]["labels"][3], "Wed. 1 January")
            self.assertEqual(response[0]["data"][3], 4.0)

            with freeze_time("2020-01-02 23:30"):
                event_factory(team=self.team, event="sign up", distinct_id="blabla")

            # test today + hourly
            with freeze_time("2020-01-02T23:31:00Z"):
                response = trends().run(
                    Filter(data={"date_from": "dStart", "interval": "hour", "events": [{"id": "sign up"}]}), self.team
                )
            self.assertEqual(response[0]["labels"][23], "Thu. 2 January, 23:00")
            self.assertEqual(response[0]["data"][23], 1.0)

        def test_breakdown_filtering(self):
            self._create_events()
            # test breakdown filtering
            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$some_property",
                            "events": [
                                {"id": "sign up", "name": "sign up", "type": "events", "order": 0,},
                                {"id": "no events"},
                            ],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["label"], "sign up - Other")
            self.assertEqual(response[1]["label"], "sign up - other_value")
            self.assertEqual(response[2]["label"], "sign up - value")
            self.assertEqual(response[3]["label"], "no events - Other")

            self.assertEqual(sum(response[0]["data"]), 2)
            self.assertEqual(response[0]["data"][4 + 7], 2)
            self.assertEqual(response[0]["breakdown_value"], "nan")

            self.assertEqual(sum(response[1]["data"]), 1)
            self.assertEqual(response[1]["data"][5 + 7], 1)
            self.assertEqual(response[1]["breakdown_value"], "other_value")

            # check numerical breakdown
            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$some_numerical_prop",
                            "events": [
                                {"id": "sign up", "name": "sign up", "type": "events", "order": 0,},
                                {"id": "no events"},
                            ],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["label"], "sign up - Other")
            self.assertEqual(response[0]["count"], 4.0)
            self.assertEqual(response[1]["label"], "sign up - 80")
            self.assertEqual(response[1]["count"], 1.0)
            self.assertTrue(
                "aggregated_value" not in response[0]
            )  # should not have aggregated value unless it's a table or pie query

        def test_breakdown_filtering_limit(self):
            self._create_breakdown_events()
            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$some_property",
                            "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(len(response), 20)

        def test_action_filtering(self):
            sign_up_action, person = self._create_events()
            action_response = trends().run(Filter(data={"actions": [{"id": sign_up_action.id}]}), self.team)
            event_response = trends().run(Filter(data={"events": [{"id": "sign up"}]}), self.team)
            self.assertEqual(len(action_response), 1)

            self.assertEntityResponseEqual(action_response, event_response)

        def test_trends_for_non_existing_action(self):
            with freeze_time("2020-01-04"):
                response = trends().run(Filter(data={"actions": [{"id": 50000000}]}), self.team)
            self.assertEqual(len(response), 0)

            with freeze_time("2020-01-04"):
                response = trends().run(Filter(data={"events": [{"id": "DNE"}]}), self.team)
            self.assertEqual(response[0]["data"], [0, 0, 0, 0, 0, 0, 0, 0])

        def test_dau_filtering(self):
            sign_up_action, person = self._create_events()

            with freeze_time("2020-01-02"):
                person_factory(team_id=self.team.pk, distinct_ids=["someone_else"])
                event_factory(team=self.team, event="sign up", distinct_id="someone_else")

            calculate_action(sign_up_action.id)

            with freeze_time("2020-01-04"):
                action_response = trends().run(
                    Filter(data={"actions": [{"id": sign_up_action.id, "math": "dau"}]}), self.team
                )
                response = trends().run(Filter(data={"events": [{"id": "sign up", "math": "dau"}]}), self.team)

            self.assertEqual(response[0]["data"][4], 1)
            self.assertEqual(response[0]["data"][5], 2)
            self.assertEntityResponseEqual(action_response, response)

        def test_dau_with_breakdown_filtering(self):
            sign_up_action, _ = self._create_events()
            with freeze_time("2020-01-02"):
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": "other_value"},
                )
            with freeze_time("2020-01-04"):
                action_response = trends().run(
                    Filter(data={"breakdown": "$some_property", "actions": [{"id": sign_up_action.id, "math": "dau"}]}),
                    self.team,
                )
                event_response = trends().run(
                    Filter(data={"breakdown": "$some_property", "events": [{"id": "sign up", "math": "dau"}]}),
                    self.team,
                )

            self.assertEqual(event_response[0]["label"], "sign up - other_value")
            self.assertEqual(event_response[1]["label"], "sign up - value")
            self.assertEqual(event_response[2]["label"], "sign up - Other")

            self.assertEqual(sum(event_response[0]["data"]), 1)
            self.assertEqual(event_response[0]["data"][5], 1)

            self.assertEqual(sum(event_response[2]["data"]), 1)
            self.assertEqual(event_response[2]["data"][4], 1)  # property not defined

            self.assertEntityResponseEqual(action_response, event_response)

        def _create_maths_events(self, values):
            sign_up_action, person = self._create_events()
            person_factory(team_id=self.team.pk, distinct_ids=["someone_else"])
            for value in values:
                event_factory(
                    team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": value}
                )
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": None})
            calculate_actions_from_last_calculation()
            return sign_up_action

        def _test_math_property_aggregation(self, math_property, values, expected_value):
            sign_up_action = self._create_maths_events(values)

            action_response = trends().run(
                Filter(
                    data={"actions": [{"id": sign_up_action.id, "math": math_property, "math_property": "some_number"}]}
                ),
                self.team,
            )
            event_response = trends().run(
                Filter(data={"events": [{"id": "sign up", "math": math_property, "math_property": "some_number"}]}),
                self.team,
            )
            # :TRICKY: Work around clickhouse functions not being 100%
            self.assertAlmostEqual(action_response[0]["data"][-1], expected_value, delta=0.5)
            self.assertEntityResponseEqual(action_response, event_response)

        def test_sum_filtering(self):
            self._test_math_property_aggregation("sum", values=[2, 3, 5.5, 7.5], expected_value=18)

        def test_avg_filtering(self):
            self._test_math_property_aggregation("avg", values=[2, 3, 5.5, 7.5], expected_value=4.5)

        def test_min_filtering(self):
            self._test_math_property_aggregation("min", values=[2, 3, 5.5, 7.5], expected_value=2)

        def test_max_filtering(self):
            self._test_math_property_aggregation("max", values=[2, 3, 5.5, 7.5], expected_value=7.5)

        def test_median_filtering(self):
            self._test_math_property_aggregation("median", values=range(101, 201), expected_value=150)

        def test_p90_filtering(self):
            self._test_math_property_aggregation("p90", values=range(101, 201), expected_value=190)

        def test_p95_filtering(self):
            self._test_math_property_aggregation("p95", values=range(101, 201), expected_value=195)

        def test_p99_filtering(self):
            self._test_math_property_aggregation("p99", values=range(101, 201), expected_value=199)

        def test_avg_filtering_non_number_resiliency(self):
            sign_up_action, person = self._create_events()
            person_factory(team_id=self.team.pk, distinct_ids=["someone_else"])
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 2})
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": "x"})
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": None})
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 8})
            calculate_actions_from_last_calculation()
            action_response = trends().run(
                Filter(data={"actions": [{"id": sign_up_action.id, "math": "avg", "math_property": "some_number"}]}),
                self.team,
            )
            event_response = trends().run(
                Filter(data={"events": [{"id": "sign up", "math": "avg", "math_property": "some_number"}]}), self.team
            )
            self.assertEqual(action_response[0]["data"][-1], 5)
            self.assertEntityResponseEqual(action_response, event_response)

        def test_per_entity_filtering(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-7d",
                            "events": [
                                {"id": "sign up", "properties": [{"key": "$some_property", "value": "value"}],},
                                {"id": "sign up", "properties": [{"key": "$some_property", "value": "other_value"}],},
                            ],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(response[0]["data"][4], 1)
            self.assertEqual(response[0]["count"], 1)
            self.assertEqual(response[1]["labels"][5], "Thu. 2 January")
            self.assertEqual(response[1]["data"][5], 1)
            self.assertEqual(response[1]["count"], 1)

        def _create_multiple_people(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1"], properties={"name": "person1"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person1", timestamp="2020-01-01T12:00:00Z",
            )

            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"name": "person2"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-01T12:00:00Z",
            )
            event_factory(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
            )
            # same day
            event_factory(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
            )

            person3 = person_factory(team_id=self.team.pk, distinct_ids=["person3"], properties={"name": "person3"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-01T12:00:00Z",
            )
            event_factory(
                team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-02T12:00:00Z",
            )
            event_factory(
                team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-03T12:00:00Z",
            )

            person4 = person_factory(team_id=self.team.pk, distinct_ids=["person4"], properties={"name": "person4"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person4", timestamp="2020-01-05T12:00:00Z",
            )

            return (person1, person2, person3, person4)

        def test_person_property_filtering(self):
            self._create_multiple_people()
            with freeze_time("2020-01-04"):
                response = trends().run(
                    Filter(
                        data={
                            "properties": [{"key": "name", "value": "person1", "type": "person",}],
                            "events": [{"id": "watched movie"}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(response[0]["data"][4], 1.0)
            self.assertEqual(response[0]["labels"][5], "Thu. 2 January")
            self.assertEqual(response[0]["data"][5], 0)

        def test_breakdown_by_empty_cohort(self):
            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-04T12:00:00Z",
            )

            with freeze_time("2020-01-04T13:01:01Z"):
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": json.dumps(["all"]),
                            "breakdown_type": "cohort",
                            "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(event_response[0]["label"], "$pageview - all users")
            self.assertEqual(sum(event_response[0]["data"]), 1)

        def test_breakdown_by_cohort(self):
            person1, person2, person3, person4 = self._create_multiple_people()
            cohort = cohort_factory(name="cohort1", team=self.team, groups=[{"properties": {"name": "person1"}}])
            cohort2 = cohort_factory(name="cohort2", team=self.team, groups=[{"properties": {"name": "person2"}}])
            cohort3 = cohort_factory(
                name="cohort3",
                team=self.team,
                groups=[{"properties": {"name": "person1"}}, {"properties": {"name": "person2"}},],
            )
            action = action_factory(name="watched movie", team=self.team)
            action.calculate_events()

            with freeze_time("2020-01-04T13:01:01Z"):
                action_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": json.dumps([cohort.pk, cohort2.pk, cohort3.pk, "all"]),
                            "breakdown_type": "cohort",
                            "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                        }
                    ),
                    self.team,
                )
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": json.dumps([cohort.pk, cohort2.pk, cohort3.pk, "all"]),
                            "breakdown_type": "cohort",
                            "events": [{"id": "watched movie", "name": "watched movie", "type": "events", "order": 0,}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(event_response[0]["label"], "watched movie - cohort1")
            self.assertEqual(event_response[1]["label"], "watched movie - cohort2")
            self.assertEqual(event_response[2]["label"], "watched movie - cohort3")
            self.assertEqual(event_response[3]["label"], "watched movie - all users")

            self.assertEqual(sum(event_response[0]["data"]), 1)
            self.assertEqual(event_response[0]["breakdown_value"], cohort.pk)

            self.assertEqual(sum(event_response[1]["data"]), 3)
            self.assertEqual(event_response[1]["breakdown_value"], cohort2.pk)

            self.assertEqual(sum(event_response[2]["data"]), 4)
            self.assertEqual(event_response[2]["breakdown_value"], cohort3.pk)

            self.assertEqual(sum(event_response[3]["data"]), 7)
            self.assertEqual(event_response[3]["breakdown_value"], "all")
            self.assertEntityResponseEqual(
                event_response, action_response,
            )

        def test_interval_filtering_breakdown(self):
            self._create_events(use_time=True)
            cohort = cohort_factory(name="cohort1", team=self.team, groups=[{"properties": {"$some_prop": "some_val"}}])

            # test minute
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "2020-01-01",
                            "interval": "minute",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["labels"][6], "Wed. 1 January, 00:06")
            self.assertEqual(response[0]["data"][6], 3.0)

            # test hour
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "2019-12-24",
                            "interval": "hour",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][3], "Tue. 24 December, 03:00")
            self.assertEqual(response[0]["data"][3], 1.0)
            # 217 - 24 - 1
            self.assertEqual(response[0]["data"][192], 3.0)

            # test week
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "2019-11-24",
                            "interval": "week",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][4], "Sun. 22 December")
            self.assertEqual(response[0]["data"][4], 1.0)
            self.assertEqual(response[0]["labels"][5], "Sun. 29 December")
            self.assertEqual(response[0]["data"][5], 4.0)

            # test month
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "2019-9-24",
                            "interval": "month",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][2], "Sun. 1 December")
            self.assertEqual(response[0]["data"][2], 1.0)
            self.assertEqual(response[0]["labels"][3], "Wed. 1 January")
            self.assertEqual(response[0]["data"][3], 4.0)

            with freeze_time("2020-01-02 23:30"):
                event_factory(team=self.team, event="sign up", distinct_id="blabla")

            # test today + hourly
            with freeze_time("2020-01-02T23:31:00Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "dStart",
                            "interval": "hour",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][23], "Thu. 2 January, 23:00")
            self.assertEqual(response[0]["data"][23], 1.0)

        def test_breakdown_by_person_property(self):
            person1, person2, person3, person4 = self._create_multiple_people()
            action = action_factory(name="watched movie", team=self.team)

            with freeze_time("2020-01-04T13:01:01Z"):
                action_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "name",
                            "breakdown_type": "person",
                            "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                        }
                    ),
                    self.team,
                )
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "name",
                            "breakdown_type": "person",
                            "events": [{"id": "watched movie", "name": "watched movie", "type": "events", "order": 0,}],
                        }
                    ),
                    self.team,
                )

            self.assertListEqual(
                sorted([res["breakdown_value"] for res in event_response]), ["person1", "person2", "person3", "person4"]
            )

            for response in event_response:
                if response["breakdown_value"] == "person1":
                    self.assertEqual(response["count"], 1)
                    self.assertEqual(response["label"], "watched movie - person1")
                if response["breakdown_value"] == "person2":
                    self.assertEqual(response["count"], 3)
                if response["breakdown_value"] == "person3":
                    self.assertEqual(response["count"], 3)
                if response["breakdown_value"] == "person4":
                    self.assertEqual(response["count"], 0)

            self.assertEntityResponseEqual(
                event_response, action_response,
            )

        def test_breakdown_by_person_property_pie(self):
            self._create_multiple_people()

            with freeze_time("2020-01-04T13:01:01Z"):
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "name",
                            "breakdown_type": "person",
                            "display": "ActionsPie",
                            "events": [
                                {
                                    "id": "watched movie",
                                    "name": "watched movie",
                                    "type": "events",
                                    "order": 0,
                                    "math": "dau",
                                }
                            ],
                        }
                    ),
                    self.team,
                )
                self.assertDictContainsSubset({"breakdown_value": "person1", "aggregated_value": 1}, event_response[0])
                self.assertDictContainsSubset({"breakdown_value": "person2", "aggregated_value": 1}, event_response[1])
                self.assertDictContainsSubset({"breakdown_value": "person3", "aggregated_value": 1}, event_response[2])

        def test_lifecycle_trend(self):

            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-11T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-12T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-13T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-17T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-19T12:00:00Z",
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-09T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-12T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-01-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-01-15T12:00:00Z",
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -2, -1, 0, -2, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [1, 1, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 0, 0, 0])

        def test_lifecycle_trend_prop_filtering(self):

            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-11T12:00:00Z",
                properties={"$number": 1},
            )
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-12T12:00:00Z",
                properties={"$number": 1},
            )
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-13T12:00:00Z",
                properties={"$number": 1},
            )

            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-15T12:00:00Z",
                properties={"$number": 1},
            )

            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-17T12:00:00Z",
                properties={"$number": 1},
            )

            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-19T12:00:00Z",
                properties={"$number": 1},
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-09T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-12T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-01-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-01-15T12:00:00Z",
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                        "properties": [{"key": "$number", "value": 1}],
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, 0, -1, 0, -1, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [1, 1, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [0, 0, 0, 1, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [0, 0, 0, 0, 0, 0, 0, 0])

        def test_lifecycle_trends_distinct_id_repeat(self):
            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1", "another_p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-12T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="another_p1", timestamp="2020-01-14T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-17T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-19T12:00:00Z",
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])

            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -1, 0, 0, -1, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [0, 0, 0, 1, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [0, 0, 1, 0, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 0, 0, 0, 0, 0, 0])

        def test_lifecycle_trend_people(self):

            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-11T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-12T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-13T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-17T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-19T12:00:00Z",
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-09T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-12T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-01-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-01-15T12:00:00Z",
            )

            result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team.pk,
                relative_date_parse("2020-01-13T00:00:00Z"),
                "returning",
            )

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["id"], p1.pk)

            dormant_result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team.pk,
                relative_date_parse("2020-01-13T00:00:00Z"),
                "dormant",
            )

            self.assertEqual(len(dormant_result), 2)

            dormant_result = trends().get_people(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team.pk,
                relative_date_parse("2020-01-14T00:00:00Z"),
                "dormant",
            )

            self.assertEqual(len(dormant_result), 1)

        def test_lifecycle_trend_people_paginated(self):
            for i in range(150):
                person_id = "person{}".format(i)
                person_factory(team_id=self.team.pk, distinct_ids=[person_id])
                event_factory(
                    team=self.team, event="$pageview", distinct_id=person_id, timestamp="2020-01-15T12:00:00Z",
                )
            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            result = self.client.get(
                "/api/person/lifecycle",
                data={
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                    "events": json.dumps([{"id": "$pageview", "type": "events", "order": 0}]),
                    "shown_as": TRENDS_LIFECYCLE,
                    "lifecycle_type": "new",
                    "target_date": "2020-01-15T00:00:00Z",
                },
            ).json()
            self.assertEqual(len(result["results"][0]["people"]), 100)

            second_result = self.client.get(result["next"]).json()
            self.assertEqual(len(second_result["results"][0]["people"]), 50)

        def test_lifecycle_trend_action(self):

            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-11T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-12T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-13T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-17T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-19T12:00:00Z",
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-09T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-12T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-01-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-01-15T12:00:00Z",
            )

            pageview_action = action_factory(team=self.team, name="$pageview")

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-01-12T00:00:00Z",
                        "date_to": "2020-01-19T00:00:00Z",
                        "actions": [{"id": pageview_action.pk, "type": "actions", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -2, -1, 0, -2, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [1, 1, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 0, 0, 0])

        def test_lifecycle_trend_all_time(self):

            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-11T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-12T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-13T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-17T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-19T12:00:00Z",
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-09T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-12T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-01-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-01-15T12:00:00Z",
            )

            with freeze_time("2020-01-17T13:01:01Z"):
                result = trends().run(
                    Filter(
                        data={
                            "date_from": "all",
                            "events": [{"id": "$pageview", "type": "events", "order": 0}],
                            "shown_as": TRENDS_LIFECYCLE,
                        }
                    ),
                    self.team,
                )
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -1, 0, 0, -2, -1, 0, -2, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [0, 0, 0, 1, 1, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [0, 0, 0, 1, 0, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 1, 1, 0, 0, 1, 0, 0])

        def test_lifecycle_trend_weeks(self):
            # lifecycle weeks rounds the date to the nearest following week  2/5 -> 2/10
            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-01T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-05T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-10T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-27T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-03-02T12:00:00Z",
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-02-11T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-02-18T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-02-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-02-27T12:00:00Z",
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-02-05T00:00:00Z",
                        "date_to": "2020-03-09T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                        "interval": "week",
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            self.assertTrue(
                result[0]["days"] == ["2020-02-09", "2020-02-16", "2020-02-23", "2020-03-01", "2020-03-08"]
                or result[0]["days"] == ["2020-02-10", "2020-02-17", "2020-02-24", "2020-03-02", "2020-03-09"]
            )
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -2, -1, -1, -1])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [1, 1, 0, 1, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [0, 0, 1, 0, 0])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [2, 0, 1, 0, 0])

        def test_lifecycle_trend_months(self):

            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-11T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-02-12T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-03-13T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-05-15T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-07-17T12:00:00Z",
            )

            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-09-19T12:00:00Z",
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2019-12-09T12:00:00Z",
            )
            event_factory(
                team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-02-12T12:00:00Z",
            )

            p3 = person_factory(team_id=self.team.pk, distinct_ids=["p3"], properties={"name": "p3"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-02-12T12:00:00Z",
            )

            p4 = person_factory(team_id=self.team.pk, distinct_ids=["p4"], properties={"name": "p4"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p4", timestamp="2020-05-15T12:00:00Z",
            )

            result = trends().run(
                Filter(
                    data={
                        "date_from": "2020-02-01T00:00:00Z",
                        "date_to": "2020-09-01T00:00:00Z",
                        "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        "shown_as": TRENDS_LIFECYCLE,
                        "interval": "month",
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 4)
            self.assertEqual(sorted([res["status"] for res in result]), ["dormant", "new", "resurrecting", "returning"])
            for res in result:
                if res["status"] == "dormant":
                    self.assertEqual(res["data"], [0, -2, -1, 0, -2, 0, -1, 0])
                elif res["status"] == "returning":
                    self.assertEqual(res["data"], [1, 1, 0, 0, 0, 0, 0, 0])
                elif res["status"] == "resurrecting":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 1, 0, 1])
                elif res["status"] == "new":
                    self.assertEqual(res["data"], [1, 0, 0, 1, 0, 0, 0, 0])

        def test_filter_test_accounts(self):
            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-11T12:00:00Z",
                properties={"key": "val"},
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p2",
                timestamp="2020-01-11T12:00:00Z",
                properties={"key": "val"},
            )
            self.team.test_account_filters = [{"key": "name", "value": "p1", "operator": "is_not", "type": "person"}]
            self.team.save()
            data = {
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "filter_test_accounts": "true",
            }
            filter = Filter(data=data)
            filter_2 = Filter(data={**data, "filter_test_accounts": "false",})
            filter_3 = Filter(data={**data, "breakdown": "key"})
            result = trends().run(filter, self.team,)
            self.assertEqual(result[0]["count"], 1)
            result = trends().run(filter_2, self.team,)
            self.assertEqual(result[0]["count"], 2)
            result = trends().run(filter_3, self.team,)
            self.assertEqual(result[0]["count"], 1)

    return TestTrends


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    action.calculate_events()
    return action


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups)
    cohort.calculate_people()
    return cohort


class TestDjangoTrends(trend_test_factory(Trends, Event.objects.create, Person.objects.create, _create_action, _create_cohort)):  # type: ignore
    pass

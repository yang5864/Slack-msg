import base64
import json
import sys
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import check_slack
import midnight_report
import miss_tracker
import send_slack
import test_notifications
from config import (
    FIXED_FINE_AMOUNT,
    FULL_EXEMPT_DATES,
    MEMBERS,
    PENDING_MEMBERS,
    SLACK_CHANNEL_ID,
    STUDY_START_DATE,
    active_members,
)


KST = ZoneInfo("Asia/Seoul")


class StudyBotTests(unittest.TestCase):
    def test_second_season_configuration(self):
        self.assertEqual(SLACK_CHANNEL_ID, "C0C562P5YK0")
        self.assertEqual(STUDY_START_DATE, date(2026, 10, 1))
        self.assertEqual(FIXED_FINE_AMOUNT, 1_000)
        self.assertEqual(len(MEMBERS), 9)
        self.assertEqual(PENDING_MEMBERS, ())
        self.assertEqual(MEMBERS["U0C6VD4LY3S"], "김수현")
        self.assertEqual(MEMBERS["U0C5SPBRHKQ"], "홍상우")
        self.assertEqual(len(active_members(date(2026, 10, 1))), 9)
        self.assertEqual(len(active_members(date(2026, 10, 2))), 9)

    def test_morning_message_describes_unlimited_exemptions(self):
        message = send_slack.build_morning_message(date(2026, 10, 1))
        self.assertIn("10월 01일", message)
        self.assertIn("횟수 제한 없이", message)

    def test_weekday_holidays_are_exempt(self):
        self.assertEqual(FULL_EXEMPT_DATES, {
            date(2026, 10, 5): "개천절 대체공휴일",
            date(2026, 10, 9): "한글날",
            date(2026, 12, 25): "성탄절",
        })
        self.assertIn("전원 면제일", send_slack.build_morning_message(date(2026, 10, 5)))

    @patch("check_slack.record_misses")
    @patch("check_slack.post_message")
    @patch("check_slack.thread_replies", return_value=[])
    @patch("check_slack.channel_history")
    def test_holiday_morning_post_does_not_suppress_final_notice(
        self, history, _replies, post_message, record_misses
    ):
        record_misses.return_value = {}
        history.return_value = [{
            "ts": "100.0",
            "text": send_slack.build_morning_message(date(2026, 10, 5)),
        }]

        check_slack.check_and_notify(datetime(2026, 10, 6, 9, 9, tzinfo=KST))

        message = post_message.call_args.args[0]
        self.assertIn("📋 *[10월 05일 분량] 전원 면제일*", message)
        self.assertIn("*전체 누적 벌금액: 0원*", message)
        record_misses.assert_called_once_with(date(2026, 10, 5), [])

    def test_exemption_reason_parsing_and_judging(self):
        reason = check_slack.extract_exemption_reason("면제권 사용(사유: 병원 진료)")
        self.assertEqual(reason, "병원 진료")
        self.assertTrue(check_slack.judge_exemption_reason(reason)[0])
        self.assertFalse(check_slack.judge_exemption_reason("게임하고 싶음")[0])

    @patch("check_slack.record_misses")
    @patch("check_slack.post_message")
    @patch("check_slack.thread_replies")
    @patch("check_slack.channel_history")
    def test_each_missing_member_is_charged_fixed_fine(self, history, replies, post_message, record_misses):
        member_ids = list(active_members(date(2026, 10, 1)))
        record_misses.return_value = {user_id: 2 for user_id in member_ids[:7]}
        record_misses.return_value["U0C5SPBRHKQ"] = 1
        history.return_value = [{"ts": "100.0", "text": "*[10월 01일] 오늘의 인증!*"}]
        replies.return_value = [
            {"ts": "100.0", "text": "parent"},
            {
                "ts": "101.0",
                "user": member_ids[0],
                "files": [{"mimetype": "image/png"}],
            },
            {
                "ts": "102.0",
                "user": member_ids[1],
                "text": "면제권 사용(사유: 병원 진료)",
                "files": [],
            },
            {
                "ts": "103.0",
                "user": "U0C6VD4LY3S",
                "files": [{"mimetype": "image/png"}],
            },
        ]

        check_slack.check_and_notify(datetime(2026, 10, 2, 9, 9, tzinfo=KST))

        message = post_message.call_args.args[0]
        self.assertIn("1인당 1,000원", message)
        self.assertIn(f"<@{member_ids[2]}> ({MEMBERS[member_ids[2]]}): 2회 · *2,000원*", message)
        self.assertIn("이번 발생액 합계: *6,000원*", message)
        self.assertIn("*전체 누적 벌금액: 15,000원*", message)
        self.assertIn("<@U0C6VD4LY3S> (김수현): 0회 · *0원*", message)
        self.assertIn("<@U0C5SPBRHKQ> (홍상우): 1회 · *1,000원*", message)
        self.assertNotIn("<@U0C6VD4LY3S> (김수현): 이번", message)
        self.assertIn("<@U0C5SPBRHKQ> (홍상우): 이번 *1,000원*", message)
        self.assertIn("지금 송금하지 않아도 됩니다", message)
        self.assertNotIn("카카오뱅크", message)
        self.assertIn("면제권 승인 (횟수 제한 없음)", message)
        record_misses.assert_called_once_with(date(2026, 10, 1), member_ids[2:7] + [member_ids[8]])

    @patch("check_slack.record_misses")
    @patch("check_slack.post_message")
    @patch("check_slack.thread_replies")
    @patch("check_slack.channel_history")
    def test_all_submitted_notice_includes_cumulative_amount(
        self, history, replies, post_message, record_misses
    ):
        member_ids = list(active_members(date(2026, 10, 1)))
        history.return_value = [{"ts": "100.0", "text": "*[10월 01일] 오늘의 인증!*"}]
        replies.return_value = [
            {"ts": "100.0", "text": "parent"},
            *[
                {"ts": str(101 + index), "user": user_id, "files": [{"mimetype": "image/png"}]}
                for index, user_id in enumerate(member_ids)
            ],
        ]
        record_misses.return_value = {member_ids[0]: 2, member_ids[1]: 1}

        check_slack.check_and_notify(datetime(2026, 10, 2, 9, 9, tzinfo=KST))

        message = post_message.call_args.args[0]
        self.assertIn("전원 제출 완료", message)
        self.assertIn(f"<@{member_ids[0]}> ({MEMBERS[member_ids[0]]}): 2회 · *2,000원*", message)
        self.assertIn(f"<@{member_ids[2]}> ({MEMBERS[member_ids[2]]}): 0회 · *0원*", message)
        self.assertIn("*전체 누적 벌금액: 3,000원*", message)
        record_misses.assert_called_once_with(date(2026, 10, 1), [])

    def test_miss_counts_are_derived_from_dated_records(self):
        records = {
            "2026-10-01": ["U1", "U2"],
            "2026-10-02": ["U1"],
            "2026-10-05": [],
        }
        self.assertEqual(miss_tracker.count_misses(records), {"U1": 2, "U2": 1})

    @patch("miss_tracker.load_records")
    def test_repeat_check_does_not_increase_count(self, load_records):
        load_records.return_value = ({"2026-10-01": ["U1"]}, "existing-sha")
        self.assertEqual(miss_tracker.record_misses(date(2026, 10, 1), ["U1"]), {"U1": 1})

    @patch("miss_tracker.load_records")
    def test_repeat_check_with_changed_result_requires_manual_review(self, load_records):
        load_records.return_value = ({"2026-10-01": ["U1"]}, "existing-sha")
        with self.assertRaises(RuntimeError):
            miss_tracker.record_misses(date(2026, 10, 1), ["U2"])

    @patch("miss_tracker._github_context", return_value=("test-token", "owner/repo"))
    @patch("miss_tracker.load_records", return_value=({}, "existing-sha"))
    def test_new_miss_record_is_saved_once(self, _load_records, _github_context):
        response = SimpleNamespace(raise_for_status=lambda: None)
        fake_requests = SimpleNamespace(put=unittest.mock.Mock(return_value=response))
        with patch.dict(sys.modules, {"requests": fake_requests}):
            counts = miss_tracker.record_misses(date(2026, 10, 1), ["U2", "U1"])

        self.assertEqual(counts, {"U1": 1, "U2": 1})
        payload = fake_requests.put.call_args.kwargs["json"]
        saved = json.loads(base64.b64decode(payload["content"]))
        self.assertEqual(saved, {"missed_dates": {"2026-10-01": ["U1", "U2"]}})
        self.assertEqual(payload["sha"], "existing-sha")

    @patch("test_notifications.post_message")
    def test_three_test_messages_are_clearly_marked(self, post_message):
        test_notifications.send_test_notifications()

        self.assertEqual(post_message.call_count, 3)
        for call in post_message.call_args_list:
            message = call.args[0]
            self.assertIn("[2기 테스트]", message)
            self.assertNotIn("오늘의 인증!", message)
            self.assertNotIn("10월 01일", message)

    @patch("midnight_report.post_message")
    @patch("midnight_report.thread_replies")
    @patch("midnight_report.channel_history")
    def test_midnight_ignores_test_parent(self, history, replies, post_message):
        history.return_value = [
            {"ts": "100.0", "text": "[2기 테스트] *[10월 01일] 오늘의 인증!*"}
        ]

        midnight_report.send_midnight_report(datetime(2026, 10, 2, 0, 0, tzinfo=KST))

        replies.assert_not_called()
        post_message.assert_not_called()

    @patch("check_slack.post_message")
    @patch("check_slack.thread_replies")
    @patch("check_slack.channel_history")
    def test_check_ignores_test_parent(self, history, replies, post_message):
        history.return_value = [
            {"ts": "100.0", "text": "[2기 테스트] *[10월 01일] 오늘의 인증!*"}
        ]

        check_slack.check_and_notify(datetime(2026, 10, 2, 9, 9, tzinfo=KST))

        replies.assert_not_called()
        post_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()

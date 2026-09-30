import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import check_slack
import send_slack
from config import FIXED_FINE_AMOUNT, MEMBERS, SLACK_CHANNEL_ID, STUDY_START_DATE


KST = ZoneInfo("Asia/Seoul")


class StudyBotTests(unittest.TestCase):
    def test_second_season_configuration(self):
        self.assertEqual(SLACK_CHANNEL_ID, "C0C562P5YK0")
        self.assertEqual(STUDY_START_DATE, date(2026, 10, 1))
        self.assertEqual(FIXED_FINE_AMOUNT, 1_000)
        self.assertEqual(len(MEMBERS), 7)

    def test_morning_message_describes_unlimited_exemptions(self):
        message = send_slack.build_morning_message(date(2026, 10, 1))
        self.assertIn("10월 01일", message)
        self.assertIn("횟수 제한 없이", message)

    def test_exemption_reason_parsing_and_judging(self):
        reason = check_slack.extract_exemption_reason("면제권 사용(사유: 병원 진료)")
        self.assertEqual(reason, "병원 진료")
        self.assertTrue(check_slack.judge_exemption_reason(reason)[0])
        self.assertFalse(check_slack.judge_exemption_reason("게임하고 싶음")[0])

    @patch("check_slack.post_message")
    @patch("check_slack.thread_replies")
    @patch("check_slack.channel_history")
    def test_each_missing_member_is_charged_fixed_fine(self, history, replies, post_message):
        member_ids = list(MEMBERS)
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
        ]

        check_slack.check_and_notify(datetime(2026, 10, 2, 9, 9, tzinfo=KST))

        message = post_message.call_args.args[0]
        self.assertIn("1인당 1,000원", message)
        self.assertIn("총액: *5,000원*", message)
        self.assertIn("면제권 승인 (횟수 제한 없음)", message)


if __name__ == "__main__":
    unittest.main()

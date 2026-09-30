import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import check_slack
import midnight_report
import send_slack
import test_notifications
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

import unittest
from unittest.mock import MagicMock, patch

import lark.feishu_mapping as feishu_mapping
from lark.feishu_mapping import resolve_open_id


class ResolveOpenIdTest(unittest.TestCase):
    def setUp(self) -> None:
        feishu_mapping._mapping = {"user@example.com": "ou_from_email"}

    def tearDown(self) -> None:
        feishu_mapping._mapping = None

    def test_returns_empty_when_name_and_email_missing(self) -> None:
        client = MagicMock()
        self.assertEqual(resolve_open_id(client, None, None), "")

    def test_resolves_by_email_from_mapping(self) -> None:
        client = MagicMock()
        result = resolve_open_id(client, "张三", "user@example.com")
        self.assertEqual(result, "ou_from_email")

    @patch.object(feishu_mapping, "DEFAULT_CONFIG", {"notify_department_id": "od_test"})
    @patch.object(feishu_mapping, "_find_users_by_department")
    def test_resolves_by_name_when_only_name_provided(self, mock_find_users) -> None:
        mock_find_users.return_value = {"张三": "ou_from_name"}
        client = MagicMock()

        result = resolve_open_id(client, name="张三", email=None)

        self.assertEqual(result, "ou_from_name")
        mock_find_users.assert_called_once_with(client, "od_test")

    @patch.object(feishu_mapping, "DEFAULT_CONFIG", {"notify_department_id": "od_test"})
    @patch.object(feishu_mapping, "_find_users_by_department")
    def test_name_lookup_is_case_insensitive(self, mock_find_users) -> None:
        mock_find_users.return_value = {"zhangsan": "ou_lower"}
        client = MagicMock()

        result = resolve_open_id(client, name="ZhangSan", email=None)

        self.assertEqual(result, "ou_lower")

    @patch.object(feishu_mapping, "DEFAULT_CONFIG", {"notify_department_id": None})
    def test_returns_empty_when_only_name_and_department_not_configured(self) -> None:
        client = MagicMock()
        self.assertEqual(resolve_open_id(client, "张三", None), "")

    @patch.object(feishu_mapping, "DEFAULT_CONFIG", {"notify_department_id": "od_test"})
    @patch.object(feishu_mapping, "_find_users_by_department")
    def test_returns_empty_when_name_not_found_in_department(self, mock_find_users) -> None:
        mock_find_users.return_value = {"李四": "ou_other"}
        client = MagicMock()

        result = resolve_open_id(client, name="张三", email=None)

        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()

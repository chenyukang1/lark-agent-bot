import unittest
from unittest.mock import patch

from app.lark import users
from app.lark.users import resolve_open_id


class ResolveOpenIdTest(unittest.TestCase):
    def setUp(self) -> None:
        users._mapping = {"user@example.com": "ou_from_email"}

    def tearDown(self) -> None:
        users._mapping = None

    def test_returns_empty_when_name_and_email_missing(self) -> None:
        self.assertEqual(resolve_open_id(name=None, email=None), "")

    def test_resolves_by_email_from_mapping(self) -> None:
        result = resolve_open_id(name="张三", email="user@example.com")
        self.assertEqual(result, "ou_from_email")

    @patch.object(users, "get_config", new=lambda: {"notify_department_id": "od_test"})
    @patch.object(users, "_find_users_by_department")
    def test_resolves_by_name_when_only_name_provided(self, mock_find_users) -> None:
        mock_find_users.return_value = {"张三": "ou_from_name"}

        result = resolve_open_id(name="张三", email=None)

        self.assertEqual(result, "ou_from_name")
        mock_find_users.assert_called_once_with("od_test")

    @patch.object(users, "get_config", new=lambda: {"notify_department_id": "od_test"})
    @patch.object(users, "_find_users_by_department")
    def test_name_lookup_is_case_insensitive(self, mock_find_users) -> None:
        mock_find_users.return_value = {"zhangsan": "ou_lower"}

        result = resolve_open_id(name="ZhangSan", email=None)

        self.assertEqual(result, "ou_lower")

    @patch.object(users, "get_config", new=lambda: {"notify_department_id": None})
    def test_returns_empty_when_only_name_and_department_not_configured(self) -> None:
        self.assertEqual(resolve_open_id(name="张三", email=None), "")

    @patch.object(users, "get_config", new=lambda: {"notify_department_id": "od_test"})
    @patch.object(users, "_find_users_by_department")
    def test_returns_empty_when_name_not_found_in_department(
        self, mock_find_users
    ) -> None:
        mock_find_users.return_value = {"李四": "ou_other"}
        result = resolve_open_id(name="张三", email=None)

        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()

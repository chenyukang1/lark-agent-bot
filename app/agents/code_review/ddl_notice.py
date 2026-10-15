from app.lark import get_lark_client


class DDLNoticeAgent:
    def __init__(self) -> None:
        self._lark_client = get_lark_client()

    def review_code(self):
        pass

    def send_ddl_notice(self, notice_report: str):
        pass

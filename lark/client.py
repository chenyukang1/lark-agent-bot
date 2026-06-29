import lark_oapi as lark
from lark_oapi.core.enum import LogLevel
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler


class LarkApiClient(object):
    def __init__(self):
        self.client = lark.Client.builder().app_id(lark.APP_ID).app_secret(lark.APP_SECRET).build()

# 创建 LarkClient 对象，用于请求OpenAPI, 并创建 LarkWSClient 对象，用于使用长连接接收事件。
# Create LarkClient object for requesting OpenAPI, and create LarkWSClient object for receiving events using long connection.
class LarkClient(object):
    def __init__(self, log_level: LogLevel = LogLevel.INFO):
        self.app_id = lark.APP_ID
        self.app_secret = lark.APP_SECRET
        self.log_level = log_level

    def register_event_handler(self, event_handler: EventDispatcherHandler):
        self.event_handler = event_handler

    def start(self):
        if not self.event_handler:
            raise ValueError("Event handler is not registered")

        client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=self.event_handler,
            log_level=self.log_level,
        )

        client.start()

lark_api_client = LarkApiClient()
lark_client = LarkClient(log_level=LogLevel.DEBUG)
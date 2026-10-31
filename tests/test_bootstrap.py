import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from app import bootstrap


class BootstrapTest(unittest.TestCase):
    def test_main_initializes_handlers_and_connects_lark_client(self):
        calls = MagicMock()
        names = (
            "load_dotenv", "setup_logging", "load_user_mapping",
            "start_webhook_server", "get_lark_client",
            "P2ImMessageReceiveV1Handler",
            "P2ImChatAccessEventBotP2PChatEnteredV1Handler",
            "P2CardActionTriggerHandler",
        )
        with ExitStack() as stack:
            mocks = {
                name: stack.enter_context(patch.object(bootstrap, name))
                for name in names
            }
            for name, mock in mocks.items():
                calls.attach_mock(mock, name)
            dispatcher = stack.enter_context(
                patch.object(bootstrap.lark_oapi, "EventDispatcherHandler")
            )
            builder = dispatcher.builder.return_value
            builder.register_p2_im_message_receive_v1.return_value = builder
            builder.register_p2_im_chat_access_event_bot_p2p_chat_entered_v1.return_value = builder
            builder.register_p2_card_action_trigger.return_value = builder
            bootstrap.main()

        self.assertEqual(
            [call[0] for call in calls.mock_calls[:4]],
            ["load_dotenv", "setup_logging", "load_user_mapping", "start_webhook_server"],
        )
        connection = mocks["get_lark_client"].return_value
        connection.register_event_handler.assert_called_once_with(builder.build.return_value)
        connection.start.assert_called_once_with()
        event = object()
        builder.register_p2_im_message_receive_v1.call_args.args[0](event)
        mocks["P2ImMessageReceiveV1Handler"].return_value.handle.assert_called_once_with(event)
        builder.register_p2_im_chat_access_event_bot_p2p_chat_entered_v1.call_args.args[0](event)
        mocks["P2ImChatAccessEventBotP2PChatEnteredV1Handler"].return_value.handle.assert_called_once_with(event)
        builder.register_p2_card_action_trigger.call_args.args[0](event)
        mocks["P2CardActionTriggerHandler"].return_value.handle.assert_called_once_with(event)

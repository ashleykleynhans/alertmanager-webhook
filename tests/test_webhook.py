"""Tests for the Alertmanager webhook receiver."""
import builtins
import copy
import importlib
import json
import sys
from typing import Any
from unittest.mock import MagicMock, mock_open, patch

import pytest
import yaml

import webhook
from helpers import TEST_CONFIG, config_open, make_alert, make_payload, real_open


def _handler_context(payload: dict) -> Any:
    """Create a POST request context for handler tests."""
    return webhook.app.test_request_context(
        '/critical',
        method='POST',
        data=json.dumps(payload),
        content_type='application/json',
    )


# ---------------------------------------------------------------------------
# get_args
# ---------------------------------------------------------------------------
class TestGetArgs:
    """Tests for command line argument parsing."""

    def test_default_args(self) -> None:
        """Default host and port are used when no args provided."""
        with patch('sys.argv', ['webhook.py']):
            args = webhook.get_args()
        assert args.port == 8090
        assert args.host == '0.0.0.0'

    def test_custom_args(self) -> None:
        """Custom host and port are parsed from CLI args."""
        with patch('sys.argv', ['webhook.py', '-p', '9090', '-H', '127.0.0.1']):
            args = webhook.get_args()
        assert args.port == 9090
        assert args.host == '127.0.0.1'


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------
class TestLoadConfig:
    """Tests for configuration file loading."""

    def test_success(self) -> None:
        """Config is loaded and parsed from YAML file."""
        test_data = {'key': 'value'}
        with patch('builtins.open', mock_open(read_data=yaml.dump(test_data))):
            result = webhook.load_config()
        assert result == test_data

    def test_file_not_found(self) -> None:
        """SystemExit is raised when config file is missing."""
        with patch('builtins.open', side_effect=FileNotFoundError):
            with pytest.raises(SystemExit):
                webhook.load_config()


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------
class TestValidateConfig:
    """Tests for configuration validation."""

    def test_none_config(self) -> None:
        """Exception raised for None config."""
        with pytest.raises(Exception, match='does not appear to contain any data'):
            webhook.validate_config(None)

    def test_no_discord_no_telegram(self) -> None:
        """KeyError raised when neither discord nor telegram configured."""
        with pytest.raises(KeyError, match='Neither'):
            webhook.validate_config({'valid_environments': []})

    def test_discord_no_bot_token(self) -> None:
        """KeyError raised when discord missing bot_token."""
        with pytest.raises(KeyError, match='bot_token'):
            webhook.validate_config({'discord': {}})

    def test_telegram_no_bot_token(self) -> None:
        """KeyError raised when telegram missing bot_token."""
        with pytest.raises(KeyError, match='bot_token'):
            webhook.validate_config({'telegram': {}})

    def test_discord_no_environments(self) -> None:
        """KeyError raised when discord missing environments."""
        with pytest.raises(KeyError, match='environments'):
            webhook.validate_config({'discord': {'bot_token': 'x'}})

    def test_telegram_no_environments(self) -> None:
        """KeyError raised when telegram missing environments."""
        with pytest.raises(KeyError, match='environments'):
            webhook.validate_config({'telegram': {'bot_token': 'x'}})

    def test_pagerduty_no_environments(self) -> None:
        """KeyError raised when pagerduty missing environments."""
        conf = {
            'discord': {'bot_token': 'x', 'environments': {}},
            'pagerduty': {},
            'valid_environments': [],
            'default_environment': '',
            'environment_mapping': {},
        }
        with pytest.raises(KeyError, match='environments'):
            webhook.validate_config(conf)

    def test_pagerduty_no_services(self) -> None:
        """KeyError raised when pagerduty missing services."""
        conf = {
            'discord': {'bot_token': 'x', 'environments': {}},
            'pagerduty': {'environments': []},
            'valid_environments': [],
            'default_environment': '',
            'environment_mapping': {},
        }
        with pytest.raises(KeyError, match='services'):
            webhook.validate_config(conf)

    def test_discord_no_channel_id(self) -> None:
        """KeyError raised when discord environment missing channel_id."""
        conf = {
            'discord': {
                'bot_token': 'x',
                'environments': {'prod': {'critical': {}}},
            },
            'valid_environments': [],
            'default_environment': '',
            'environment_mapping': {},
        }
        with pytest.raises(KeyError, match='channel_id'):
            webhook.validate_config(conf)

    def test_discord_no_author(self) -> None:
        """KeyError raised when discord environment missing author."""
        conf = {
            'discord': {
                'bot_token': 'x',
                'environments': {'prod': {'critical': {'channel_id': '1'}}},
            },
            'valid_environments': [],
            'default_environment': '',
            'environment_mapping': {},
        }
        with pytest.raises(KeyError, match='author'):
            webhook.validate_config(conf)

    def test_telegram_no_chat_id(self) -> None:
        """KeyError raised when telegram environment missing chat_id."""
        conf = {
            'telegram': {
                'bot_token': 'x',
                'environments': {'prod': {'critical': {}}},
            },
            'valid_environments': [],
            'default_environment': '',
            'environment_mapping': {},
        }
        with pytest.raises(KeyError, match='chat_id'):
            webhook.validate_config(conf)

    def test_no_valid_environments(self) -> None:
        """KeyError raised when valid_environments missing."""
        conf = {'discord': {'bot_token': 'x', 'environments': {}}}
        with pytest.raises(KeyError, match='valid_environments'):
            webhook.validate_config(conf)

    def test_no_default_environment(self) -> None:
        """KeyError raised when default_environment missing."""
        conf = {
            'discord': {'bot_token': 'x', 'environments': {}},
            'valid_environments': [],
        }
        with pytest.raises(KeyError, match='default_environment'):
            webhook.validate_config(conf)

    def test_no_environment_mapping(self) -> None:
        """KeyError raised when environment_mapping missing."""
        conf = {
            'discord': {'bot_token': 'x', 'environments': {}},
            'valid_environments': [],
            'default_environment': '',
        }
        with pytest.raises(KeyError, match='environment_mapping'):
            webhook.validate_config(conf)

    def test_valid_config(self) -> None:
        """Full valid config passes validation without errors."""
        webhook.validate_config(copy.deepcopy(TEST_CONFIG))


# ---------------------------------------------------------------------------
# substitute_hyperlinks
# ---------------------------------------------------------------------------
class TestSubstituteHyperlinks:
    """Tests for Slack-style hyperlink conversion."""

    def test_html_format(self) -> None:
        """Slack links converted to HTML anchor tags."""
        text = 'Visit <https://example.com|Example Site> now'
        result = webhook.substitute_hyperlinks(text, 'html')
        assert result == 'Visit <a href="https://example.com">Example Site</a> now'

    def test_markdown_format(self) -> None:
        """Slack links converted to Markdown links."""
        text = 'Visit <http://example.com|Example> now'
        result = webhook.substitute_hyperlinks(text, 'markdown')
        assert result == 'Visit [Example](http://example.com) now'

    def test_unsupported_format(self) -> None:
        """Exception raised for unsupported link format."""
        with pytest.raises(Exception, match='Unsupported link format'):
            webhook.substitute_hyperlinks('<https://x.com|X>', 'bbcode')

    def test_no_matches(self) -> None:
        """Text without links returned unchanged."""
        text = 'No links here'
        assert webhook.substitute_hyperlinks(text) == text

    def test_multiple_links(self) -> None:
        """Multiple Slack links in same text all converted."""
        text = '<https://a.com|A> and <https://b.com|B>'
        result = webhook.substitute_hyperlinks(text, 'html')
        assert '<a href="https://a.com">A</a>' in result
        assert '<a href="https://b.com">B</a>' in result


# ---------------------------------------------------------------------------
# parse_alert_message
# ---------------------------------------------------------------------------
class TestParseAlertMessage:
    """Tests for alert message formatting per notification system."""

    def test_telegram(self) -> None:
        """Telegram format uses HTML bold tags."""
        result = webhook.parse_alert_message('telegram', 'Host', 'web-01')
        assert result == '<b>Host</b>: web-01'

    def test_discord(self) -> None:
        """Discord format uses Markdown bold."""
        result = webhook.parse_alert_message('discord', 'Host', 'web-01')
        assert result == '**Host**: web-01'

    def test_pagerduty(self) -> None:
        """PagerDuty format uses plain text."""
        result = webhook.parse_alert_message('pagerduty', 'Host', 'web-01')
        assert result == 'Host: web-01'

    def test_unknown_system(self) -> None:
        """Unknown notification system uses plain text fallback."""
        result = webhook.parse_alert_message('slack', 'Host', 'web-01')
        assert result == 'Host: web-01'


# ---------------------------------------------------------------------------
# parse_alert
# ---------------------------------------------------------------------------
class TestParseAlert:
    """Tests for alert payload parsing."""

    def test_watchdog_ignored(self) -> None:
        """Watchdog alerts return all-None tuple."""
        alert = make_alert(alertname='Watchdog')
        result = webhook.parse_alert(alert, 'critical', 'discord')
        assert result == (None, None, None, None, None, None, None)

    def test_firing_with_all_fields(self) -> None:
        """Firing alert with all labels and annotations parsed correctly."""
        alert = make_alert(
            status='firing',
            hostname='web-server-01',
            app='myapp',
            summary='HTTPS://example.com High CPU',
            description='<b>CPU at 99%</b>',
            extra_labels={'log': '/var/log/app.log'},
            extra_annotations={
                'info': 'Additional info',
                'runbook_url': 'http://runbooks.example.com/cpu',
            },
        )
        title, desc, hostname, status, application, env, severity = \
            webhook.parse_alert(alert, 'warning', 'discord')

        assert 'EXAMPLE.COM HIGH CPU' in title
        assert 'HTTPS://' not in title
        assert hostname == 'web-server-01'
        assert status == 'firing'
        assert application == 'myapp'
        assert env == 'prod'
        assert severity == 'critical'
        assert '**Environment**' in desc
        assert '**App**' in desc
        assert '**Hostname**' in desc
        assert '**Info**' in desc
        assert '&lt;b&gt;CPU at 99%&lt;/b&gt;' in desc
        assert '**Runbook URL**' in desc
        assert '**Log**' in desc
        assert '**Started**' in desc

    def test_resolved_status(self) -> None:
        """Resolved alert includes end time in description."""
        alert = make_alert(
            status='resolved',
            ends_at='2024-10-06T02:00:00.00Z',
        )
        title, desc, *_ = webhook.parse_alert(alert, 'critical', 'telegram')

        assert 'RESOLVED' in title
        assert '<b>Resolved</b>' in desc

    def test_unknown_status(self) -> None:
        """Unknown status skips date information."""
        alert = make_alert(status='pending')
        _, desc, *_ = webhook.parse_alert(alert, 'critical', 'discord')

        assert 'Started' not in desc
        assert 'Resolved' not in desc

    def test_nodename_label(self) -> None:
        """Nodename used as hostname when hostname absent."""
        alert = make_alert(hostname=None)
        alert['labels']['nodename'] = 'node-01'
        _, desc, hostname, *_ = webhook.parse_alert(alert, 'critical', 'discord')

        assert hostname == 'node-01'
        assert 'Instance' in desc

    def test_node_label(self) -> None:
        """Node label used when hostname and nodename absent."""
        alert = make_alert(hostname=None)
        alert['labels']['node'] = 'k8s-node-01'
        _, desc, hostname, *_ = webhook.parse_alert(alert, 'critical', 'discord')

        assert hostname == 'k8s-node-01'
        assert 'Node' in desc

    def test_instance_label(self) -> None:
        """Instance label used when hostname, nodename, and node absent."""
        alert = make_alert(hostname=None)
        alert['labels']['instance'] = '10.0.0.1:9090'
        _, desc, hostname, *_ = webhook.parse_alert(alert, 'critical', 'discord')

        assert hostname == '10.0.0.1:9090'
        assert 'Instance' in desc

    def test_no_host_labels(self) -> None:
        """Empty hostname when no host labels present."""
        alert = make_alert(hostname=None)
        _, _, hostname, *_ = webhook.parse_alert(alert, 'critical', 'discord')
        assert hostname == ''

    def test_severity_from_default(self) -> None:
        """Default severity used when not in alert labels."""
        alert = make_alert(severity=None)
        *_, severity = webhook.parse_alert(alert, 'warning', 'discord')
        assert severity == 'warning'

    def test_no_summary(self) -> None:
        """Title is just status when summary annotation missing."""
        alert = make_alert(summary=None)
        title, *_ = webhook.parse_alert(alert, 'critical', 'discord')
        assert title == 'FIRING'

    def test_no_environment_label(self) -> None:
        """Default environment used when label missing."""
        alert = make_alert(environment=None)
        *_, env, _ = webhook.parse_alert(alert, 'critical', 'discord')
        assert env == 'prod'

    def test_environment_mapping(self) -> None:
        """Environment mapped via environment_mapping config."""
        alert = make_alert(environment='ip-172-17-1-170.us-east-2.internal')
        *_, env, _ = webhook.parse_alert(alert, 'critical', 'discord')
        assert env == 'test'

    def test_invalid_environment_falls_back(self) -> None:
        """Invalid unmapped environment falls back to default."""
        alert = make_alert(environment='eu-west-1')
        *_, env, _ = webhook.parse_alert(alert, 'critical', 'discord')
        assert env == 'prod'

    def test_no_description_annotation(self) -> None:
        """Alert without description annotation still parses."""
        alert = make_alert(description=None)
        _, desc, *_ = webhook.parse_alert(alert, 'critical', 'pagerduty')
        assert 'Description' not in desc

    def test_no_info_annotation(self) -> None:
        """Alert without info annotation still parses."""
        alert = make_alert()
        _, desc, *_ = webhook.parse_alert(alert, 'critical', 'discord')
        assert 'Info' not in desc

    def test_no_app_label(self) -> None:
        """Alert without app label still parses."""
        alert = make_alert(app=None)
        _, desc, _, _, application, *_ = webhook.parse_alert(alert, 'critical', 'discord')
        assert application == ''
        assert 'App' not in desc


# ---------------------------------------------------------------------------
# discord_handler
# ---------------------------------------------------------------------------
class TestDiscordHandler:
    """Tests for the Discord notification handler."""

    def _mock_response(self, status_code: int = 200, body: dict = None) -> MagicMock:
        """Create a mock requests response."""
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = body or {'id': '12345'}
        return resp

    def test_not_configured(self) -> None:
        """Returns 404 when discord not in config."""
        del webhook.config['discord']
        payload = make_payload()
        with _handler_context(payload):
            result = webhook.discord_handler('critical')
        assert result.status_code == 404

    def test_firing_critical(self) -> None:
        """Firing critical alert sends red embed."""
        payload = make_payload(alerts=[make_alert(severity='critical')])
        with patch('webhook.requests.post', return_value=self._mock_response()):
            with _handler_context(payload):
                result = webhook.discord_handler('critical')
        assert len(result) == 1

    def test_firing_warning(self) -> None:
        """Firing warning alert sends yellow embed."""
        payload = make_payload(alerts=[make_alert(severity='warning')])
        with patch('webhook.requests.post', return_value=self._mock_response()):
            with _handler_context(payload):
                result = webhook.discord_handler('warning')
        assert len(result) == 1

    def test_firing_info(self) -> None:
        """Firing info alert sends blue embed."""
        payload = make_payload(alerts=[make_alert(severity='info')])
        with patch('webhook.requests.post', return_value=self._mock_response()):
            with _handler_context(payload):
                result = webhook.discord_handler('info')
        assert len(result) == 1

    def test_firing_unknown_severity(self) -> None:
        """Firing alert with unknown severity sends default yellow embed."""
        payload = make_payload(alerts=[make_alert(severity='custom')])
        with patch('webhook.requests.post', return_value=self._mock_response()):
            with _handler_context(payload):
                result = webhook.discord_handler('custom')
        assert len(result) == 1

    def test_resolved(self) -> None:
        """Resolved alert sends green embed."""
        payload = make_payload(
            alerts=[make_alert(status='resolved', severity='critical')],
            status='resolved',
        )
        with patch('webhook.requests.post', return_value=self._mock_response()):
            with _handler_context(payload):
                result = webhook.discord_handler('critical')
        assert len(result) == 1

    def test_watchdog_skipped(self) -> None:
        """Watchdog alerts are skipped."""
        payload = make_payload(alerts=[make_alert(alertname='Watchdog')])
        with _handler_context(payload):
            result = webhook.discord_handler('critical')
        assert len(result) == 0

    def test_rate_limit_retry(self) -> None:
        """Handler retries on 429 rate limit response."""
        rate_limited = self._mock_response(429, {'retry_after': 0.001})
        success = self._mock_response(200)
        payload = make_payload(alerts=[make_alert(severity='critical')])

        with patch('webhook.requests.post', side_effect=[rate_limited, success]):
            with patch('webhook.time.sleep'):
                with _handler_context(payload):
                    result = webhook.discord_handler('critical')
        assert len(result) == 1

    def test_error_status_code(self) -> None:
        """Error status codes are logged."""
        payload = make_payload(alerts=[make_alert(severity='critical')])
        with patch('webhook.requests.post', return_value=self._mock_response(500)):
            with _handler_context(payload):
                result = webhook.discord_handler('critical')
        assert len(result) == 1


# ---------------------------------------------------------------------------
# telegram_handler
# ---------------------------------------------------------------------------
class TestTelegramHandler:
    """Tests for the Telegram notification handler."""

    def _mock_response(self, status_code: int = 200, body: dict = None) -> MagicMock:
        """Create a mock requests response."""
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = body or {'ok': True}
        return resp

    def test_not_configured(self) -> None:
        """Returns 404 when telegram not in config."""
        del webhook.config['telegram']
        payload = make_payload()
        with _handler_context(payload):
            result = webhook.telegram_handler('critical')
        assert result.status_code == 404

    def test_success(self) -> None:
        """Alert sent successfully to Telegram."""
        payload = make_payload(alerts=[make_alert(severity='critical')])
        with patch('webhook.requests.post', return_value=self._mock_response()):
            with _handler_context(payload):
                result = webhook.telegram_handler('critical')
        assert len(result) == 1

    def test_watchdog_skipped(self) -> None:
        """Watchdog alerts are skipped."""
        payload = make_payload(alerts=[make_alert(alertname='Watchdog')])
        with _handler_context(payload):
            result = webhook.telegram_handler('critical')
        assert len(result) == 0

    def test_environment_not_configured(self) -> None:
        """Alerts for unconfigured environments are skipped."""
        payload = make_payload(alerts=[make_alert(environment='test')])
        with _handler_context(payload):
            result = webhook.telegram_handler('critical')
        assert len(result) == 0

    def test_severity_not_configured(self) -> None:
        """Alerts for unconfigured severities are skipped."""
        payload = make_payload(alerts=[make_alert(severity='info')])
        with _handler_context(payload):
            result = webhook.telegram_handler('info')
        assert len(result) == 0

    def test_rate_limit_retry(self) -> None:
        """Handler retries on 429 rate limit response."""
        rate_limited = self._mock_response(429, {'retry_after': 0.001})
        success = self._mock_response(200)
        payload = make_payload(alerts=[make_alert(severity='critical')])

        with patch('webhook.requests.post', side_effect=[rate_limited, success]):
            with patch('webhook.time.sleep'):
                with _handler_context(payload):
                    result = webhook.telegram_handler('critical')
        assert len(result) == 1

    def test_error_status_code(self) -> None:
        """Error status codes are logged."""
        payload = make_payload(alerts=[make_alert(severity='critical')])
        with patch('webhook.requests.post', return_value=self._mock_response(500)):
            with _handler_context(payload):
                result = webhook.telegram_handler('critical')
        assert len(result) == 1


# ---------------------------------------------------------------------------
# pagerduty_handler
# ---------------------------------------------------------------------------
class TestPagerdutyHandler:
    """Tests for the PagerDuty notification handler."""

    def _mock_response(self, status_code: int = 202, body: dict = None) -> MagicMock:
        """Create a mock requests response."""
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = body or {'status': 'success', 'dedup_key': 'abc'}
        return resp

    def test_not_configured(self) -> None:
        """Returns 404 when pagerduty not in config."""
        del webhook.config['pagerduty']
        payload = make_payload()
        with _handler_context(payload):
            result = webhook.pagerduty_handler('critical')
        assert result.status_code == 404

    def test_non_critical_skipped(self) -> None:
        """Non-critical alerts return empty response."""
        payload = make_payload(alerts=[make_alert(severity='warning')])
        with _handler_context(payload):
            result = webhook.pagerduty_handler('warning')
        assert result == []

    def test_watchdog_skipped(self) -> None:
        """Watchdog alerts are skipped via severity check."""
        payload = make_payload(alerts=[make_alert(alertname='Watchdog')])
        with _handler_context(payload):
            result = webhook.pagerduty_handler('critical')
        assert result == []

    def test_none_title_description_skipped(self) -> None:
        """Alerts with no title or description are skipped."""
        payload = make_payload(alerts=[make_alert(severity='critical')])
        with patch('webhook.parse_alert',
                   return_value=(None, None, 'host', 'firing', 'app', 'prod', 'critical')):
            with _handler_context(payload):
                result = webhook.pagerduty_handler('critical')
        assert len(result) == 0

    def test_firing_trigger(self) -> None:
        """Firing critical alert triggers PagerDuty incident."""
        payload = make_payload(alerts=[make_alert(severity='critical')])
        with patch('webhook.requests.post', return_value=self._mock_response()) as mock_post:
            with _handler_context(payload):
                result = webhook.pagerduty_handler('critical')

        assert len(result) == 1
        call_data = json.loads(mock_post.call_args.kwargs['data'])
        assert call_data['event_action'] == 'trigger'
        assert call_data['dedup_key'] == 'abc123'

    def test_resolved_resolve(self) -> None:
        """Resolved critical alert resolves PagerDuty incident."""
        payload = make_payload(
            alerts=[make_alert(status='resolved', severity='critical')],
            status='resolved',
        )
        with patch('webhook.requests.post', return_value=self._mock_response()) as mock_post:
            with _handler_context(payload):
                result = webhook.pagerduty_handler('critical')

        assert len(result) == 1
        call_data = json.loads(mock_post.call_args.kwargs['data'])
        assert call_data['event_action'] == 'resolve'
        assert call_data['dedup_key'] == 'abc123'

    def test_unknown_status_skipped(self) -> None:
        """Unknown status alerts are skipped."""
        payload = make_payload(alerts=[make_alert(status='pending', severity='critical')])
        with _handler_context(payload):
            result = webhook.pagerduty_handler('critical')
        assert len(result) == 0

    def test_environment_not_configured(self) -> None:
        """Alerts for unconfigured environments are skipped."""
        payload = make_payload(alerts=[make_alert(environment='test', severity='critical')])
        with _handler_context(payload):
            result = webhook.pagerduty_handler('critical')
        assert len(result) == 0

    def test_service_from_hostname_regex(self) -> None:
        """Service extracted from hostname via regex pattern."""
        payload = make_payload(alerts=[
            make_alert(hostname='snap-test-prod', severity='critical'),
        ])
        with patch('webhook.requests.post', return_value=self._mock_response()) as mock_post:
            with _handler_context(payload):
                webhook.pagerduty_handler('critical')

        call_data = json.loads(mock_post.call_args.kwargs['data'])
        assert call_data['routing_key'] == 'test-routing-key-snap'

    def test_service_from_application(self) -> None:
        """Service falls back to application name."""
        payload = make_payload(alerts=[
            make_alert(hostname='12345', app='rds', severity='critical'),
        ])
        with patch('webhook.requests.post', return_value=self._mock_response()) as mock_post:
            with _handler_context(payload):
                webhook.pagerduty_handler('critical')

        call_data = json.loads(mock_post.call_args.kwargs['data'])
        assert call_data['routing_key'] == 'test-routing-key-rds'

    def test_service_from_hostname_exact(self) -> None:
        """Service falls back to exact hostname match in services."""
        payload = make_payload(alerts=[
            make_alert(hostname='snap', app='unknown', severity='critical'),
        ])
        with patch('webhook.requests.post', return_value=self._mock_response()) as mock_post:
            with _handler_context(payload):
                webhook.pagerduty_handler('critical')

        call_data = json.loads(mock_post.call_args.kwargs['data'])
        assert call_data['routing_key'] == 'test-routing-key-snap'

    def test_service_default(self) -> None:
        """Service falls back to default when no match found."""
        payload = make_payload(alerts=[
            make_alert(hostname='12345', app='unknown', severity='critical'),
        ])
        with patch('webhook.requests.post', return_value=self._mock_response()) as mock_post:
            with _handler_context(payload):
                webhook.pagerduty_handler('critical')

        call_data = json.loads(mock_post.call_args.kwargs['data'])
        assert call_data['routing_key'] == 'test-routing-key-default'

    def test_service_not_in_config_uses_default_key(self) -> None:
        """Routing key falls back to default when extracted service not in config."""
        payload = make_payload(alerts=[
            make_alert(hostname='unknown-prod', severity='critical'),
        ])
        with patch('webhook.requests.post', return_value=self._mock_response()) as mock_post:
            with _handler_context(payload):
                webhook.pagerduty_handler('critical')

        call_data = json.loads(mock_post.call_args.kwargs['data'])
        assert call_data['routing_key'] == 'test-routing-key-default'

    def test_empty_hostname_replaced(self) -> None:
        """Empty hostname replaced with 'none' for PagerDuty source."""
        payload = make_payload(alerts=[
            make_alert(hostname=None, app=None, severity='critical'),
        ])
        with patch('webhook.requests.post', return_value=self._mock_response()) as mock_post:
            with _handler_context(payload):
                webhook.pagerduty_handler('critical')

        call_data = json.loads(mock_post.call_args.kwargs['data'])
        assert call_data['payload']['source'] == 'none'

    def test_missing_fingerprint(self) -> None:
        """Empty dedup_key when fingerprint missing from alert."""
        payload = make_payload(alerts=[
            make_alert(fingerprint=None, severity='critical'),
        ])
        with patch('webhook.requests.post', return_value=self._mock_response()) as mock_post:
            with _handler_context(payload):
                webhook.pagerduty_handler('critical')

        call_data = json.loads(mock_post.call_args.kwargs['data'])
        assert call_data['dedup_key'] == ''

    def test_rate_limit_retry(self) -> None:
        """Handler retries on 429 rate limit response."""
        rate_limited = self._mock_response(429, {'retry_after': 0.001})
        success = self._mock_response(202)
        payload = make_payload(alerts=[make_alert(severity='critical')])

        with patch('webhook.requests.post', side_effect=[rate_limited, success]):
            with patch('webhook.time.sleep'):
                with _handler_context(payload):
                    result = webhook.pagerduty_handler('critical')
        assert len(result) == 1

    def test_error_status_code(self) -> None:
        """Non-200/202 status codes are logged."""
        payload = make_payload(alerts=[make_alert(severity='critical')])
        with patch('webhook.requests.post', return_value=self._mock_response(500)):
            with _handler_context(payload):
                result = webhook.pagerduty_handler('critical')
        assert len(result) == 1

    def test_success_200(self) -> None:
        """200 status code accepted as success."""
        payload = make_payload(alerts=[make_alert(severity='critical')])
        with patch('webhook.requests.post', return_value=self._mock_response(200)):
            with _handler_context(payload):
                result = webhook.pagerduty_handler('critical')
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------
class TestRoutes:
    """Tests for Flask route handlers."""

    def test_ping(self, client: Any) -> None:
        """GET / returns status ok."""
        response = client.get('/')
        assert response.status_code == 200
        assert response.get_json() == {'status': 'ok'}

    def test_webhook_handler(self, client: Any) -> None:
        """POST /<severity> calls all three handlers."""
        with patch.object(webhook, 'discord_handler', return_value=[{'ok': True}]), \
             patch.object(webhook, 'telegram_handler', return_value=[{'ok': True}]), \
             patch.object(webhook, 'pagerduty_handler', return_value=[{'ok': True}]):
            response = client.post('/critical', json=make_payload())

        assert response.status_code == 200
        data = response.get_json()
        assert 'discord' in data
        assert 'telegram' in data
        assert 'pagerduty' in data

    def test_not_found(self, client: Any) -> None:
        """Unmatched URLs return custom 404 response."""
        response = client.get('/nonexistent/path')
        assert response.status_code == 404
        data = response.get_json()
        assert data['status'] == 'error'

    def test_internal_server_error(self) -> None:
        """500 error handler returns correct response."""
        with webhook.app.test_request_context('/'):
            response = webhook.internal_server_error(Exception('test error'))
        assert response.status_code == 500
        data = response.get_json()
        assert data['status'] == 'error'
        assert data['msg'] == 'Internal Server Error'


# ---------------------------------------------------------------------------
# Module-level code
# ---------------------------------------------------------------------------
class TestModuleLevel:
    """Tests for module-level initialisation code."""

    def test_linux_platform_log_path(self) -> None:
        """Log path set to /var/log/ on Linux platform."""
        original = sys.modules.pop('webhook')
        try:
            builtins.open = config_open
            with patch('sys.platform', 'linux'):
                wh = importlib.import_module('webhook')
                assert wh.log_path == '/var/log/'
        finally:
            builtins.open = real_open
            sys.modules['webhook'] = original

    def test_non_linux_platform_log_path(self) -> None:
        """Log path is empty on non-Linux platforms."""
        assert webhook.log_path == ''

"""Shared test helpers and configuration for webhook tests."""
import builtins
from typing import Any, Dict, Optional
from unittest.mock import mock_open

import yaml


TEST_CONFIG: Dict[str, Any] = {
    'discord': {
        'bot_token': 'test-discord-token',
        'environments': {
            'prod': {
                'critical': {
                    'channel_id': '123456',
                    'author': {
                        'name': 'Alertmanager',
                        'icon_url': 'http://example.com/icon.png'
                    }
                },
                'warning': {
                    'channel_id': '789012',
                    'author': {
                        'name': 'Alertmanager',
                        'icon_url': 'http://example.com/icon.png'
                    }
                },
                'info': {
                    'channel_id': '345678',
                    'author': {
                        'name': 'Alertmanager',
                        'icon_url': 'http://example.com/icon.png'
                    }
                },
                'custom': {
                    'channel_id': '999999',
                    'author': {
                        'name': 'Alertmanager',
                        'icon_url': 'http://example.com/icon.png'
                    }
                }
            },
            'test': {
                'critical': {
                    'channel_id': '111111',
                    'author': {
                        'name': 'Alertmanager',
                        'icon_url': 'http://example.com/icon.png'
                    }
                },
                'warning': {
                    'channel_id': '222222',
                    'author': {
                        'name': 'Alertmanager',
                        'icon_url': 'http://example.com/icon.png'
                    }
                }
            }
        }
    },
    'telegram': {
        'bot_token': 'test-telegram-token',
        'environments': {
            'prod': {
                'critical': {'chat_id': '-100123'},
                'warning': {'chat_id': '-100456'}
            }
        }
    },
    'pagerduty': {
        'environments': ['prod'],
        'services': {
            'default': 'test-routing-key-default',
            'snap': 'test-routing-key-snap',
            'rds': 'test-routing-key-rds'
        }
    },
    'valid_environments': ['test', 'prod'],
    'default_environment': 'prod',
    'environment_mapping': {
        'us-east-1': 'prod',
        'us-east-2': 'test'
    }
}

real_open = builtins.open


def config_open(file: str, *args: Any, **kwargs: Any) -> Any:
    """Mock open that intercepts config.yml reads."""
    if isinstance(file, str) and file == 'config.yml':
        return mock_open(read_data=yaml.dump(TEST_CONFIG))()
    return real_open(file, *args, **kwargs)


def make_alert(
    status: str = 'firing',
    alertname: str = 'TestAlert',
    severity: Optional[str] = 'critical',
    environment: Optional[str] = 'prod',
    hostname: Optional[str] = 'snap-test-prod',
    app: Optional[str] = 'rds',
    summary: Optional[str] = 'Test alert summary',
    description: Optional[str] = 'Test alert description',
    starts_at: str = '2024-10-06T01:54:00.87Z',
    ends_at: str = '2024-10-06T02:00:00.00Z',
    fingerprint: Optional[str] = 'abc123',
    extra_labels: Optional[Dict[str, str]] = None,
    extra_annotations: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a sample alert dictionary."""
    labels: Dict[str, str] = {'alertname': alertname}
    if severity is not None:
        labels['severity'] = severity
    if environment is not None:
        labels['environment'] = environment
    if hostname is not None:
        labels['hostname'] = hostname
    if app is not None:
        labels['app'] = app
    if extra_labels:
        labels.update(extra_labels)

    annotations: Dict[str, str] = {}
    if summary is not None:
        annotations['summary'] = summary
    if description is not None:
        annotations['description'] = description
    if extra_annotations:
        annotations.update(extra_annotations)

    alert: Dict[str, Any] = {
        'status': status,
        'labels': labels,
        'annotations': annotations,
        'startsAt': starts_at,
        'endsAt': ends_at,
        'generatorURL': 'http://localhost:9090/graph',
    }
    if fingerprint is not None:
        alert['fingerprint'] = fingerprint
    return alert


def make_payload(
    alerts: Optional[list] = None,
    status: str = 'firing',
) -> Dict[str, Any]:
    """Create a sample Alertmanager webhook payload."""
    if alerts is None:
        alerts = [make_alert(status=status)]
    return {
        'receiver': 'webhook-critical',
        'status': status,
        'alerts': alerts,
        'groupLabels': {},
        'commonLabels': {},
        'commonAnnotations': {},
        'externalURL': 'http://localhost:9093',
        'version': '4',
        'groupKey': '{}:{}',
        'truncatedAlerts': 0,
    }

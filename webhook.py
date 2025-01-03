#!/usr/bin/env python3
"""
Alertmanager Webhook Receiver to Send Notifications to Discord, Telegram and PagerDuty.
Handles incoming webhooks from Alertmanager and routes them to appropriate notification services.
"""

import json
import re
import sys
import argparse
import yaml
import requests
import datetime
import time
import logging
import logging.handlers
from dateutil import parser
from typing import Dict, List, Tuple, Optional, Any
from flask import Flask, request, jsonify, make_response

log_level: int = logging.DEBUG
log_path: str = ''

# Mac does not have permission to /var/log for example
if sys.platform == 'linux':
    log_path = '/var/log/'

# Set the log level for the root logger
logging.getLogger().setLevel(log_level)

# Create a stream handler for stdout
formatter: logging.Formatter = logging.Formatter('%(asctime)s : %(levelname)s : %(message)s')
stream_handler: logging.StreamHandler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
logging.getLogger().addHandler(stream_handler)


def get_args() -> argparse.Namespace:
    """
    Parse command line arguments for the webhook receiver.

    Returns:
        argparse.Namespace: Parsed command line arguments containing host and port
    """
    parser = argparse.ArgumentParser(
        description='Alertmanager Webhook Receiver to Send Notifications to Discord, Telegram and PagerDuty'
    )

    parser.add_argument(
        '-p', '--port',
        help='Port to listen on',
        type=int,
        default=8090
    )

    parser.add_argument(
        '-H', '--host',
        help='Host to bind to',
        default='0.0.0.0'
    )

    return parser.parse_args()


def load_config() -> Dict[str, Any]:
    """
    Load configuration from config.yml file.

    Returns:
        Dict[str, Any]: Configuration dictionary

    Raises:
        FileNotFoundError: If config file is not found
    """
    try:
        config_file = 'config.yml'

        with open(config_file, 'r') as stream:
            return yaml.safe_load(stream)
    except FileNotFoundError:
        print(f'ERROR: Config file {config_file} not found!')
        sys.exit()


def validate_config(conf: Optional[Dict[str, Any]]) -> None:
    """
    Validate the configuration file structure and required fields.

    Args:
        conf: Configuration dictionary to validate

    Raises:
        Exception: If config is empty
        KeyError: If required configuration keys are missing
    """
    if conf is None:
        raise Exception('config.yml does not appear to contain any data')

    if 'discord' not in conf and 'telegram' not in conf:
        raise KeyError('Neither "discord" nor "telegram" found in config.yml')

    if 'discord' in conf and 'bot_token' not in conf['discord']:
        raise KeyError('"bot_token" not found under discord section of config.yml')

    if 'telegram' in conf and 'bot_token' not in conf['telegram']:
        raise KeyError('"bot_token" not found under telegram section of config.yml')

    if 'discord' in conf and 'environments' not in conf['discord']:
        raise KeyError('"environments" not found under discord section of config.yml')

    if 'telegram' in conf and 'environments' not in conf['telegram']:
        raise KeyError('"environments" not found under telegram section of config.yml')

    if 'pagerduty' in conf and 'environments' not in conf['pagerduty']:
        raise KeyError('"environments" not found under pagerduty section of config.yml')

    if 'pagerduty' in conf and 'services' not in conf['pagerduty']:
        raise KeyError('"services" not found under pagerduty section of config.yml')

    if 'discord' in conf:
        for env in conf['discord']['environments']:
            for severity in conf['discord']['environments'][env]:
                if 'channel_id' not in conf['discord']['environments'][env][severity]:
                    raise KeyError(
                        f'"channel_id" not found for severity {severity} for the {env} environment for Discord in '
                        'config.yml'
                    )

                if 'author' not in conf['discord']['environments'][env][severity]:
                    raise KeyError(
                        f'"author" not found for severity {severity} for the {env} environment for Discord in '
                        'config.yml'
                    )

    if 'telegram' in conf:
        for env in conf['telegram']['environments']:
            for severity in conf['telegram']['environments'][env]:
                if 'chat_id' not in conf['telegram']['environments'][env][severity]:
                    raise KeyError(
                        f'"chat_id" not found for severity {severity} for the {env} environment for Telegram in '
                        'config.yml'
                    )

    if 'valid_environments' not in conf:
        raise KeyError('"valid_environments" not found in config.yml')

    if 'default_environment' not in conf:
        raise KeyError('"default_environment" not found in config.yml')

    if 'environment_mapping' not in conf:
        raise KeyError('"environment_mapping" not found in config.yml')


def substitute_hyperlinks(text: str, link_format: str = 'html') -> str:
    """
    Convert Slack-style hyperlinks to HTML or Markdown format.

    Args:
        text: Text containing Slack-style hyperlinks
        link_format: Format to convert links to ('html' or 'markdown')

    Returns:
        str: Text with converted hyperlinks

    Raises:
        Exception: If link_format is not supported
    """
    pattern = '(<(https?:\/\/.*?)\|(.*?)>)'
    matches = re.findall(pattern, text)

    if matches:
        for match in matches:
            link_original = match[0]
            link_actual = match[1]
            link_text = match[2]

            if link_format == 'html':
                link_new = f'<a href="{link_actual}">{link_text}</a>'
            elif link_format == 'markdown':
                link_new = f'[{link_text}]({link_actual})'
            else:
                raise Exception(f'Unsupported link format: {link_format}')

            text = text.replace(link_original, link_new)

    return text


def parse_alert_message(notification_system: str, title: str, message: str) -> str:
    """
    Format alert message according to notification system requirements.

    Args:
        notification_system: Type of notification system ('telegram', 'discord', or 'pagerduty')
        title: Alert title
        message: Alert message content

    Returns:
        str: Formatted message string
    """
    if notification_system == 'telegram':
        return f'<b>{title}</b>: {message}'
    elif notification_system == 'discord':
        return f'**{title}**: {message}'
    elif notification_system == 'pagerduty':
        return f'{title}: {message}'
    else:
        return f'{title}: {message}'


def parse_alert(
    alert: Dict[str, Any],
    default_severity: str,
    notification_system: str
) -> Tuple[
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str]
]:
    """
    Parse alert data into a formatted message.

    Args:
        alert: Alert data dictionary from Alertmanager
        default_severity: Default severity in the POST URL
        notification_system: Type of notification system to format for

    Returns:
        Tuple containing:
            - title: Alert title (or None if alert should be ignored)
            - description: Formatted alert description (or None if alert should be ignored)
            - hostname: Source hostname
            - status: Alert status
            - application: Application name
            - environment: Environment name
            - severity: Alert severity
    """
    title = alert['status'].upper()
    description = ''
    hostname = ''
    application = ''

    # Ignore the Watchdog alert
    if 'alertname' in alert['labels'] and alert['labels']['alertname'] == 'Watchdog':
        return None, None, None, None, None, None, None

    if 'environment' in alert['labels']:
        description += parse_alert_message(
            notification_system,
            'Environment',
            f"{alert['labels']['environment']}\n"
        )

    if 'app' in alert['labels']:
        application = alert['labels']['app']
        description += parse_alert_message(
            notification_system,
            'App',
            f"{alert['labels']['app']}\n"
        )

    if 'hostname' in alert['labels']:
        hostname = alert['labels']['hostname']
        description += parse_alert_message(
            notification_system,
            'Hostname',
            f"{alert['labels']['hostname']}\n"
        )
    elif 'nodename' in alert['labels']:
        hostname = alert['labels']['nodename']
        description += parse_alert_message(
            notification_system,
            'Instance',
            f"{alert['labels']['nodename']}\n"
        )
    elif 'node' in alert['labels']:
        hostname = alert['labels']['node']
        description += parse_alert_message(
            notification_system,
            'Node',
            f"{alert['labels']['node']}\n"
        )
    elif 'instance' in alert['labels']:
        hostname = alert['labels']['instance']
        description += parse_alert_message(
            notification_system,
            'Instance',
            f"{alert['labels']['instance']}\n"
        )

    if 'severity' in alert['labels']:
        severity = alert['labels']['severity']
    else:
        severity = default_severity

    if 'info' in alert['annotations']:
        description += parse_alert_message(
            notification_system,
            'Info',
            f"{alert['annotations']['info']}\n"
        )

    if 'summary' in alert['annotations']:
        title = f"{alert['status']} : {alert['annotations']['summary']}".upper()

    if 'description' in alert['annotations']:
        description += parse_alert_message(
            notification_system,
            'Description',
            f"{alert['annotations']['description']}\n"
        )

    if 'runbook_url' in alert['annotations']:
        description += parse_alert_message(
            notification_system,
            'Runbook URL',
            f"{alert['annotations']['runbook_url']}\n"
        )

    if 'log' in alert['labels']:
        description += parse_alert_message(
            notification_system,
            'Log',
            f"{alert['labels']['log']}\n"
        )

    status = alert['status']

    if status == 'resolved':
        correct_date = parser.parse(alert['endsAt']).strftime('%Y-%m-%d %H:%M:%S')
        description += parse_alert_message(
            notification_system,
            'Resolved',
            correct_date
        )
    elif status == 'firing':
        correct_date = parser.parse(alert['startsAt']).strftime('%Y-%m-%d %H:%M:%S')
        description += parse_alert_message(
            notification_system,
            'Started',
            correct_date
        )

    # Fall back to default environment if no environment is found in the alert
    if 'environment' not in alert['labels']:
        logging.info('[DISCORD]: No environment label, falling back to default environment')
        environment = config['default_environment']
    else:
        environment = alert['labels']['environment']

        # Check for partial environment match if the full environment is not matched
        if environment not in config['valid_environments']:
            for env in config['environment_mapping']:
                if env in environment:
                    environment = config['environment_mapping'][env]

        # No valid environment found in the alert, use the default instead
        if environment not in config['valid_environments']:
            logging.info('[DISCORD]: Invalid environment, falling back to default environment')
            environment = config['default_environment']

    return title, description, hostname, status, application, environment, severity


def discord_handler(default_severity: str):
    """
    Handle Discord notifications for alerts.

    Args:
        default_severity: Default alert severity level

    Returns:
        List[Dict[str, Any]]: List of Discord API responses
    """
    notification_system = 'discord'

    if notification_system not in config:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': f"'{notification_system}' section not found in config"
            }
        ), 404)

    payload: Dict[str, Any] = request.get_json()
    bot_token: str = config[notification_system]['bot_token']
    responses: List[Dict[str, Any]] = []

    for alert in payload['alerts']:
        (title, description, hostname, status, application,
         environment, severity) = parse_alert(alert, default_severity, notification_system)

        if title is None and description is None:
            logging.info('[DISCORD]: No title or description, no notification will be sent')
            continue

        discord_config = config[notification_system]['environments'][environment][severity]
        channel_id: str = discord_config['channel_id']
        bot_url: str = f'https://discordapp.com/api/channels/{channel_id}/messages'
        icon_url: str = discord_config['author']['icon_url']
        icon_type: str = discord_config['author']['name']

        if alert['status'] == 'firing':
            if severity == 'critical':
                color = '#E01E5A'  # Red - Critical
            elif severity == 'warning':
                color = '#ECB22E'  # Yellow - Warning
            elif severity == 'info':
                color = '#36C5F0'  # Blue - Info
            else:
                color = '#ECB22E'  # Default to yellow if severity unknown
        else:
            color = '#2EB67D'      # Green - Resolved

        color = color[1:]
        color = int(color, 16)

        embeds = [
            {
                'title': title,
                'type': 'rich',
                'description': substitute_hyperlinks(description, 'markdown'),
                'author': {
                    'name': icon_type,
                    'icon_url': icon_url
                },
                'color': color,
                'timestamp': datetime.datetime.utcnow().isoformat()
            }
        ]

        response = requests.post(
            url=bot_url,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bot {bot_token}'
            },
            json={
                'embeds': embeds
            }
        )

        discord_response = response.json()

        if response.status_code == 429:
            retry_after = discord_response['retry_after']
            logging.warning(f'[DISCORD]: API rate limiting in place, retrying after: {retry_after}')
            time.sleep(retry_after)

            response = requests.post(
                url=bot_url,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bot {bot_token}'
                },
                json={
                    'embeds': embeds
                }
            )

            discord_response = response.json()
        elif response.status_code != 200:
            logging.error(f'[DISCORD]: API returned status code: {response.status_code}')

        responses.append(discord_response)

    return responses


def telegram_handler(default_severity: str):
    """
    Handle Telegram notifications for alerts.

    Args:
        default_severity: Default alert severity level

    Returns:
        List[Dict[str, Any]]: List of Telegram API responses
    """
    notification_system = 'telegram'

    if notification_system not in config:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': f"'{notification_system}' section not found in config"
            }
        ), 404)

    payload = request.get_json()
    bot_token = config[notification_system]['bot_token']
    bot_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    responses = []

    for alert in payload['alerts']:
        (title, description, hostname, status, application,
         environment, severity) = parse_alert(alert, default_severity, notification_system)

        if title is None and description is None:
            logging.info('[TELEGRAM]: No title or description, no notification will be sent')
            continue

        if environment not in config[notification_system]['environments']:
            continue

        if severity not in config[notification_system]['environments'][environment]:
            continue

        chat_id = config[notification_system]['environments'][environment][severity]['chat_id']
        message = f'<b>{title}</b>\n\n'
        message += description

        response = requests.post(
            url=bot_url,
            data={
                'chat_id': chat_id,
                'parse_mode': 'html',
                'text': message
            }
        )

        telegram_response = response.json()

        if response.status_code == 429:
            retry_after = telegram_response['retry_after']
            logging.warning(f'[TELEGRAM]: API rate limiting in place, retrying after: {retry_after}')
            time.sleep(retry_after)

            response = requests.post(
                url=bot_url,
                data={
                    'chat_id': chat_id,
                    'parse_mode': 'html',
                    'text': message
                }
            )

            telegram_response = response.json()
        elif response.status_code != 200:
            logging.error(f'[TELEGRAM]: API returned status code: {response.status_code}')

        responses.append(telegram_response)

    return responses


def pagerduty_handler(default_severity: str):
    """
    Handle PagerDuty notifications for critical alerts.

    Args:
        default_severity: Default alert severity level

    Returns:
        List[Dict[str, Any]]: List of Telegram API responses
    """
    notification_system = 'pagerduty'
    responses = []

    if notification_system not in config:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': f"'{notification_system}' section not found in config"
            }
        ), 404)

    payload = request.get_json()
    url = 'https://events.pagerduty.com/v2/enqueue'

    for alert in payload['alerts']:
        (title, description, hostname, status, application,
         environment, severity) = parse_alert(alert, default_severity, notification_system)

        # PagerDuty is only triggered when the severity of the alert = critical
        if severity != 'critical':
            logging.info(f'[PAGERDUTY]: Severity = {severity} (not critical), no notification will be sent')
            return responses

        if title is None and description is None:
            logging.info('[PAGERDUTY]: No title or description, no notification will be sent')
            continue

        # Only continue if there is a new alert that is firing
        if status == 'firing':
            logging.info('[PAGERDUTY]: Status is firing, incident will be triggered')
            event_action = 'trigger'
        else:
            logging.info('[PAGERDUTY]: Status is not firing, no incident will be triggered')
            continue

        logging.debug(f'[PAGERDUTY]: Environment: {environment}')

        if environment not in config[notification_system]['environments']:
            continue

        pattern = r'^[a-zA-Z]+(?=[\.-])'
        match = re.match(pattern, hostname)

        if match:
            service = match.group(0)
        elif application in config[notification_system]['services']:
            service = application
        elif hostname in config[notification_system]['services']:
            service = hostname
        else:
            service = 'default'

        if service in config[notification_system]['services']:
            routing_key = config[notification_system]['services'][service]
        else:
            routing_key = config[notification_system]['services']['default']

        message = f'{title}\n\n'
        message += description

        logging.debug(f'[PAGERDUTY]: Service: {service}')
        logging.debug(f'[PAGERDUTY]: Routing Key: {routing_key}')

        # PagerDuty source field cannot be empty
        if not len(hostname):
            hostname = 'none'

        payload = {
            'payload': {
                'summary': message,
                'severity': severity,
                'source': hostname
            },
            'routing_key': routing_key,
            'event_action': event_action
        }

        response = requests.post(
            url=url,
            data=json.dumps(payload)
        )

        pagerduty_response = response.json()

        if response.status_code == 429:
            retry_after = pagerduty_response['retry_after']
            logging.warning(f'[PAGERDUTY]: API rate limiting in place, retrying after: {retry_after}')
            time.sleep(retry_after)

            response = requests.post(
                url=url,
                data=json.dumps(payload)
            )

            pagerduty_response = response.json()
        # PagerDuty usually returns HTTP status code 202
        elif response.status_code != 200 and response.status_code != 202:
            logging.error(f'[PAGERDUTY]: API returned status code: {response.status_code}')

        responses.append(pagerduty_response)

    return responses


config = load_config()
validate_config(config)
app = Flask(__name__)


@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify(
        {
            'status': 'error',
            'msg': f'{request.url} not found',
            'detail': str(error)
        }
    ), 404)


@app.errorhandler(500)
def internal_server_error(error):
    return make_response(jsonify(
        {
            'status': 'error',
            'msg': 'Internal Server Error',
            'detail': str(error)
        }
    ), 500)


@app.route('/', methods=['GET'])
def ping():
    return make_response(jsonify(
        {
            'status': 'ok'
        }
    ), 200)


@app.route(f'/<severity>', methods=['POST'])
def webhook_handler(severity):
    return make_response(jsonify(
        {
            'discord': discord_handler(severity),
            'telegram': telegram_handler(severity),
            'pagerduty': pagerduty_handler(severity)
        }
    ), 200)


if __name__ == '__main__':
    args = get_args()

    app.run(
        host=args.host,
        port=args.port
    )

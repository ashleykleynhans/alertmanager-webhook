#!/usr/bin/env python3
import re
import sys
import argparse
import yaml
import requests
import datetime
import time
from dateutil import parser
from flask import Flask, request, jsonify, make_response


def get_args():
    parser = argparse.ArgumentParser(
        description='Alertmanager Webhook Receiver to Send Notifications to Discord and Telegram'
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


def load_config():
    try:
        config_file = 'config.yml'

        with open(config_file, 'r') as stream:
            return yaml.safe_load(stream)
    except FileNotFoundError:
        print(f'ERROR: Config file {config_file} not found!')
        sys.exit()


def validate_config(conf):
    if conf is None:
        raise Exception('config.yml does not appear to contain any data')

    if 'discord' not in conf and 'telegram' not in conf:
        raise KeyError('Neither "discord" nor "telegram" found in config.yml')

    if 'discord' in conf and 'bot_token' not in conf['discord']:
        raise KeyError('"bot_token" not found under discord section of config.xml')

    if 'telegram' in conf and 'bot_token' not in conf['telegram']:
        raise KeyError('"bot_token" not found under telegram section of config.xml')

    if 'discord' in conf and 'environments' not in conf['discord']:
        raise KeyError('"environments" not found under discord section of config.xml')

    if 'telegram' in conf and 'environments' not in conf['telegram']:
        raise KeyError('"environments" not found under telegram section of config.xml')

    if 'discord' in conf:
        for env in conf['discord']['environments']:
            for severity in conf['discord']['environments'][env]:
                if 'channel_id' not in conf['discord']['environments'][env][severity]:
                    raise KeyError(f'"channel_id" not found for severity {severity} for the {env} environment for Discord in config.xml')

                if 'author' not in conf['discord']['environments'][env][severity]:
                    raise KeyError(f'"author" not found for severity {severity} for the {env} environment for Discord in config.xml')

    if 'telegram' in conf:
        for env in conf['telegram']['environments']:
            for severity in conf['telegram']['environments'][env]:
                if 'chat_id' not in conf['telegram']['environments'][env][severity]:
                    raise KeyError(f'"chat_id" not found for severity {severity} for the {env} environment for Telegram in config.xml')

    if 'valid_environments' not in conf:
        raise KeyError('"valid_environments" not found  in config.xml')

    if 'default_environment' not in conf:
        raise KeyError('"default_environment" not found  in config.xml')

    if 'environment_mapping' not in conf:
        raise KeyError('"environment_mapping" not found  in config.xml')


def substitute_hyperlinks(text, link_format='html'):
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


def parse_alert_message(notification_system, title, message):
    if notification_system == 'telegram':
        return f'<b>{title}</b>: {message}'
    elif notification_system == 'discord':
        return f'**{title}**: {message}'
    else:
        return f'{title}: {message}'


def parse_alert(alert, notification_system):
    title = alert['status'].upper()
    description = ''

    # Ignore the Watchdog alert that ensures that the alerting pipeline is functional
    if 'alertname' in alert['labels'] and alert['labels']['alertname'] == 'Watchdog':
        return None, None

    if 'environment' in alert['labels']:
        description += parse_alert_message(
            notification_system,
            'Environment',
            f"{alert['labels']['environment']}\n"
        )

    if 'app' in alert['labels']:
        description += parse_alert_message(
            notification_system,
            'App',
            f"{alert['labels']['app']}\n"
        )

    if 'name' in alert['labels']:
        description += parse_alert_message(
            notification_system,
            'Instance',
            f"{alert['labels']['instance']} ({alert['labels']['name']})\n"
        )
    elif 'instance' in alert['labels']:
        description += parse_alert_message(
            notification_system,
            'Instance',
            f"{alert['labels']['instance']}\n"
        )
    elif 'node' in alert['labels']:
        description += parse_alert_message(
            notification_system,
            'Node',
            f"{alert['labels']['node']}\n"
        )

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

    if 'log' in alert['labels']:
        description += parse_alert_message(
            notification_system,
            'Log',
            f"{alert['labels']['log']}\n"
        )

    if alert['status'] == 'resolved':
        correct_date = parser.parse(alert['endsAt']).strftime('%Y-%m-%d %H:%M:%S')
        description += parse_alert_message(
            notification_system,
            'Resolved',
            correct_date
        )
    elif alert['status'] == 'firing':
        correct_date = parser.parse(alert['startsAt']).strftime('%Y-%m-%d %H:%M:%S')
        description += parse_alert_message(
            notification_system,
            'Started',
            correct_date
        )

    return title, description


def discord_handler(severity):
    if 'discord' not in config:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': "'discord' section not found in config"
            }
        ), 404)

    payload = request.get_json()
    bot_token = config['discord']['bot_token']
    responses = []

    for alert in payload['alerts']:
        title, description = parse_alert(alert, 'discord')

        if title is None and description is None:
            continue

        # environment label must be present
        if 'environment' not in alert['labels']:
            continue

        environment = alert['labels']['environment']

        # No valid environment found in the alert, use the default instead
        if environment not in config['valid_environments']:
            for env in config['environment_mapping']:
                if env in environment:
                    environment = config['environment_mapping'][env]

        if environment not in config['valid_environments']:
            environment = config['default_environment']

        discord_config = config['discord']['environments'][environment][severity]
        channel_id = discord_config['channel_id']
        bot_url = f'https://discordapp.com/api/channels/{channel_id}/messages'
        icon_url = discord_config['author']['icon_url']
        icon_type = discord_config['author']['name']

        if alert['status'] == 'firing':
            if severity == 'critical':
                color = '#E01E5A'
            else:
                color = '#ECB22E'
        else:
            color = '#2EB67D'

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
            print(f'Discord rate limiting in place, retrying after: {retry_after}')
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
            print(f'Discord returned status code: {response.status_code}')

        responses.append(discord_response)

    return responses


def telegram_handler(severity):
    if 'telegram' not in config:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': "'telegram' section not found in config"
            }
        ), 404)

    payload = request.get_json()
    bot_token = config['telegram']['bot_token']
    bot_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    responses = []

    for alert in payload['alerts']:
        title, description = parse_alert(alert, 'telegram')

        if title is None and description is None:
            continue

        # environment label must be present
        if 'environment' not in alert['labels']:
            continue

        environment = alert['labels']['environment']

        # No valid environment found in the alert, use the default instead
        if environment not in config['valid_environments']:
            for env in config['environment_mapping']:
                if env in environment:
                    environment = config['environment_mapping'][env]

        if environment not in config['valid_environments']:
            environment = config['default_environment']

        if environment not in config['telegram']['environments']:
            continue

        if severity not in config['telegram']['environments'][environment]:
            continue

        telegram_config = config['telegram']['environments'][environment][severity]
        message = f'<b>{title}</b>\n\n'
        message += description

        response = requests.post(
            url=bot_url,
            data={
                'chat_id': telegram_config['chat_id'],
                'parse_mode': 'html',
                'text': message
            }
        )

        telegram_response = response.json()

        if response.status_code == 429:
            retry_after = telegram_response['retry_after']
            print(f'Telegram rate limiting in place, retrying after: {retry_after}')
            time.sleep(retry_after)

            response = requests.post(
                url=bot_url,
                data={
                    'chat_id': telegram_config['chat_id'],
                    'parse_mode': 'html',
                    'text': message
                }
            )

            telegram_response = response.json()
        elif response.status_code != 200:
            print(f'Telegram returned status code: {response.status_code}')

        responses.append(telegram_response)

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
            'telegram': telegram_handler(severity)
        }
    ), 200)


if __name__ == '__main__':
    args = get_args()

    app.run(
        host=args.host,
        port=args.port
    )

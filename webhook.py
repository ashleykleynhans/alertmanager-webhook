#!/usr/bin/env python3
import json
import sys
import argparse
import yaml
import requests
import datetime
from dateutil import parser
from flask import Flask, request, jsonify, make_response


def get_args():
    parser = argparse.ArgumentParser(
        description='AWS SNS Webhook Receiver to Send Slack Notifications'
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


def parse_alert(alert):
    title = f"Status: {alert['status']}"
    description = ''

    if 'name' in alert['labels']:
        description += f"Instance: {alert['labels']['instance']} ({alert['labels']['name']})\n"
    else:
        description += f"Instance: {alert['labels']['instance']}\n"

    if 'info' in alert['annotations']:
        description += f"Info: {alert['annotations']['info']}\n"

    if 'summary' in alert['annotations']:
        description += f"Summary: {alert['annotations']['summary']}\n"

    if 'description' in alert['annotations']:
        description += f"Description: {alert['annotations']['description']}\n"

    if alert['status'] == 'resolved':
        correct_date = parser.parse(alert['endsAt']).strftime('%Y-%m-%d %H:%M:%S')
        description += f'Resolved: {correct_date}'
    elif alert['status'] == 'firing':
        correct_date = parser.parse(alert['startsAt']).strftime('%Y-%m-%d %H:%M:%S')
        description += f'Started: {correct_date}'

    return title, description


def send_discord_notification(severity, channel_id):
    payload = request.get_json()
    bot_token = config['discord']['bot_token']
    icon_url = config['discord']['author']['icon_url']
    icon_type = config['discord']['author']['name']
    bot_url = f'https://discordapp.com/api/channels/{channel_id}/messages'
    embeds = []

    for alert in payload['alerts']:
        title, description = parse_alert(alert)

        embeds.append(
            {
                'title': title,
                'type': 'rich',
                'description': substitute_hyperlinks(description, 'markdown'),
                'author': {
                    'name': icon_type,
                    'icon_url': icon_url
                },
                'timestamp': datetime.datetime.utcnow().isoformat()
            }
        )

    return requests.post(
        url=bot_url,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bot {bot_token}'
        },
        json={
            'embeds': embeds
        }
    )


def send_telegram_notification(severity, chat_id):
    if severity not in config['telegram']['chat_id']:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': f"'{severity}' section not found in config"
            }
        ), 404)

    payload = request.get_json()
    bot_token = config['telegram']['bot_token']
    bot_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    responses = []

    for alert in payload['alerts']:
        title, description = parse_alert(alert)
        message = f'<b>Status: {title}</b>\n'
        message += description

        responses.append(
            requests.post(
                url=bot_url,
                data={
                    'chat_id': chat_id,
                    'parse_mode': 'html',
                    'text': message
                }
            )
        )

    return make_response(jsonify(
        {
            'status': 'ok',
            'responses': responses
        }
    ), 404)


def discord_handler(severity):
    if 'discord' not in config:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': "'discord' section not found in config"
            }
        ), 404)

    if 'bot_token' not in config['discord']:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': "'bot_token' section not found in 'discord' section of config"
            }
        ), 404)

    if 'channel_id' not in config['discord']:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': "'channel_id' section not found in 'discord' section of config"
            }
        ), 404)

    if 'author' not in config['discord']:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': "'author' section not found in 'discord' section of config"
            }
        ), 404)

    channel_id = config['discord']['channel_id']
    response = send_discord_notification(severity, channel_id)
    discord_response = response.json()

    if response.status_code != 200:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': f'Failed to send Discord notification to channel id: {channel_id}',
                'detail': discord_response
            }
        ), 500)

    return jsonify(discord_response)


def telegram_handler(severity):
    if 'telegram' not in config:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': "'telegram' section not found in config"
            }
        ), 404)

    if 'bot_token' not in config['telegram']:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': "'bot_token' section not found in 'telegram' section of config"
            }
        ), 404)

    if 'chat_id' not in config['telegram']:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': "'chat_id' section not found in 'telegram' section of config"
            }
        ), 404)

    chat_id = ''

    response = send_telegram_notification(severity, chat_id)
    telegram_response = response.json()

    if response.status_code != 200 or not telegram_response['ok']:
        return make_response(jsonify(
            {
                'status': 'error',
                'msg': f'Failed to send Telegram notification to chat id: {chat_id}',
                'detail': telegram_response
            }
        ), 500)

    return jsonify(telegram_response)


config = load_config()
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
            'status': 'ok',
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

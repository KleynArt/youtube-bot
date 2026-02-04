from __future__ import unicode_literals

import logging
import mimetypes
import os
import re
import shutil
import tempfile
import traceback
import urllib.parse
import urllib.request

from telegram.ext import CommandHandler
from telegram.ext import MessageHandler, Filters
from telegram.ext import Updater
from telegram.ext.dispatcher import run_async

import youtube_dl

if os.path.exists('.env'):
    print('Importing environment from .env...')
    for line in open('.env'):
        var = line.strip().split('=')
        if len(var) == 2:
            os.environ[var[0]] = var[1]

TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    raise RuntimeError('Missing TELEGRAM_TOKEN environment variable.')

updater = Updater(token=TOKEN)
dispatcher = updater.dispatcher

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

URL_RE = re.compile(r'(https?://\S+)')
MAX_FILE_SIZE_MB = 45

WELCOME_TEXT = (
    "🤖 *Bienvenido/a!* Soy tu bot de descargas para Telegram.\n\n"
    "Envíame un enlace y yo haré el resto:\n"
    "• *YouTube* → te preguntaré si quieres *audio* o *video*.\n"
    "• *Cualquier otro enlace directo* → lo descargo como archivo.\n\n"
    "Comandos:\n"
    "• /start → ver este mensaje\n"
    "• /help → ayuda rápida\n\n"
    "Ejemplos:\n"
    "• https://youtu.be/dQw4w9WgXcQ\n"
    "• https://example.com/archivo.zip"
)

HELP_TEXT = (
    "🧭 *Ayuda rápida*\n\n"
    "1) Envíame un enlace.\n"
    "2) Si es YouTube, responde con *audio* o *video*.\n"
    "3) Si es otro enlace, lo descargo y lo envío como archivo.\n\n"
    "Palabras clave: audio, video, archivo.\n"
    "Si tienes problemas, vuelve a enviar el enlace."
)

chat_state = {}


def start(bot, update):
    bot.sendMessage(chat_id=update.message.chat_id, text=WELCOME_TEXT, parse_mode='Markdown')


start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)


def help_command(bot, update):
    bot.sendMessage(chat_id=update.message.chat_id, text=HELP_TEXT, parse_mode='Markdown')


help_handler = CommandHandler('help', help_command)
dispatcher.add_handler(help_handler)


def extract_first_url(text):
    match = URL_RE.search(text)
    return match.group(1) if match else None


def is_youtube_link(link):
    return 'youtu' in link


def safe_filename(name):
    sanitized = name.replace(':', ' -')
    sanitized = sanitized.replace('?', '')
    sanitized = sanitized.replace('/', '_')
    sanitized = sanitized.replace('|', '_')
    sanitized = sanitized.replace('"', "'")
    return sanitized


def human_size(num_bytes):
    if num_bytes is None:
        return 'tamaño desconocido'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def download_direct_file(link):
    temp_dir = tempfile.mkdtemp(prefix='download-')
    parsed = urllib.parse.urlparse(link)
    filename = os.path.basename(parsed.path) or 'archivo'
    filename = safe_filename(filename)
    file_path = os.path.join(temp_dir, filename)

    request = urllib.request.Request(link, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request) as response:
        content_length = response.headers.get('Content-Length')
        if content_length:
            size_mb = int(content_length) / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                raise ValueError(
                    f"El archivo pesa {size_mb:.1f} MB y supera el límite de {MAX_FILE_SIZE_MB} MB."
                )
        with open(file_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

    return temp_dir, file_path


@run_async
def music(bot, update, link):
    temp_dir = None
    try:
        ydl_opts = {
            'outtmpl': '%(title)s.%(ext)s',
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
        title = ''
        bot.sendMessage(chat_id=update.message.chat_id, text='🎧 Descargando audio...')
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            title = safe_filename(info['title'])
        temp_dir = tempfile.mkdtemp(prefix='yt-audio-')
        source = f"{title}.mp3"
        target = os.path.join(temp_dir, source)
        if os.path.exists(source):
            shutil.move(source, target)
        bot.sendMessage(chat_id=update.message.chat_id, text='📤 Enviando audio...')
        bot.sendAudio(chat_id=update.message.chat_id, audio=open(target, 'rb'), title=title)
        bot.sendMessage(chat_id=update.message.chat_id, text='✅ ¡Listo!')
    except Exception:
        traceback.print_exc()
        bot.sendMessage(chat_id=update.message.chat_id, text='❌ Lo siento, algo salió mal.')
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        if title and os.path.exists(f"{title}.mp3"):
            os.remove(f"{title}.mp3")


@run_async
def video(bot, update, link):
    temp_dir = None
    try:
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': '%(title)s.%(ext)s',
        }
        title = ''
        bot.sendMessage(chat_id=update.message.chat_id, text='🎬 Descargando video...')
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            title = safe_filename(info['title'])
        temp_dir = tempfile.mkdtemp(prefix='yt-video-')
        source = f"{title}.mp4"
        target = os.path.join(temp_dir, source)
        if os.path.exists(source):
            shutil.move(source, target)
        bot.sendMessage(chat_id=update.message.chat_id, text='📤 Enviando video...')
        bot.sendVideo(chat_id=update.message.chat_id, video=open(target, 'rb'), title=title)
        bot.sendMessage(chat_id=update.message.chat_id, text='✅ ¡Listo!')
    except Exception:
        traceback.print_exc()
        bot.sendMessage(chat_id=update.message.chat_id, text='❌ Lo siento, algo salió mal.')
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        if title and os.path.exists(f"{title}.mp4"):
            os.remove(f"{title}.mp4")


@run_async
def send_direct_file(bot, update, link):
    temp_dir = None
    try:
        bot.sendMessage(chat_id=update.message.chat_id, text='📥 Descargando archivo...')
        temp_dir, file_path = download_direct_file(link)
        size = os.path.getsize(file_path)
        bot.sendMessage(
            chat_id=update.message.chat_id,
            text=f"📦 Archivo listo ({human_size(size)}). Enviando...",
        )
        mime_type, _ = mimetypes.guess_type(file_path)
        with open(file_path, 'rb') as handle:
            bot.sendDocument(
                chat_id=update.message.chat_id,
                document=handle,
                filename=os.path.basename(file_path),
                mime_type=mime_type,
            )
        bot.sendMessage(chat_id=update.message.chat_id, text='✅ ¡Enviado!')
    except ValueError as exc:
        bot.sendMessage(chat_id=update.message.chat_id, text=f'⚠️ {exc}')
    except Exception:
        traceback.print_exc()
        bot.sendMessage(chat_id=update.message.chat_id, text='❌ Lo siento, algo salió mal.')
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


@run_async
def echo(bot, update):
    text = str(update.message.text)
    link = extract_first_url(text)
    chat_id = update.message.chat_id

    if link:
        if is_youtube_link(link):
            chat_state[chat_id] = {'link': link, 'source': 'youtube'}
            bot.sendMessage(
                chat_id=chat_id,
                text='🔗 Enlace de YouTube recibido. ¿Quieres *audio* o *video*?',
                parse_mode='Markdown',
            )
            return
        chat_state[chat_id] = {'link': link, 'source': 'direct'}
        send_direct_file(bot, update, link)
        return

    lowered = text.lower()
    if lowered in ('audio', 'musica', 'música'):
        state = chat_state.get(chat_id)
        if state and state.get('source') == 'youtube':
            music(bot, update, state['link'])
        else:
            bot.sendMessage(chat_id=chat_id, text='Primero envíame un enlace de YouTube.')
        return

    if lowered in ('video', 'vídeo'):
        state = chat_state.get(chat_id)
        if state and state.get('source') == 'youtube':
            video(bot, update, state['link'])
        else:
            bot.sendMessage(chat_id=chat_id, text='Primero envíame un enlace de YouTube.')
        return

    if lowered in ('archivo', 'file'):
        state = chat_state.get(chat_id)
        if state and state.get('source') == 'direct':
            send_direct_file(bot, update, state['link'])
        else:
            bot.sendMessage(chat_id=chat_id, text='Envíame un enlace directo para descargar el archivo.')
        return

    bot.sendMessage(chat_id=chat_id, text='Hola 👋 Envíame un enlace para empezar o usa /help.')


echo_handler = MessageHandler([Filters.text], echo)
dispatcher.add_handler(echo_handler)


def unknown(bot, update):
    bot.sendMessage(chat_id=update.message.chat_id, text='🤔 No entendí ese comando. Usa /help.')


unknown_handler = MessageHandler([Filters.command], unknown)
dispatcher.add_handler(unknown_handler)

updater.start_polling()
updater.idle()

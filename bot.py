from __future__ import unicode_literals
from telegram import ReplyKeyboardMarkup
from telegram.ext import Updater
from telegram.ext import CommandHandler
from telegram.ext import MessageHandler, Filters
from telegram.ext.dispatcher import run_async
import os
import re
import time
import traceback
import urllib.request
import youtube_dl

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

if os.path.exists('.env'):
    print('Importing environment from .env...')
    for line in open('.env'):
        var = line.strip().split('=')
        if len(var) == 2:
            os.environ[var[0]] = var[1]

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise RuntimeError('Missing TELEGRAM_BOT_TOKEN environment variable.')
updater = Updater(token=TOKEN)
dispatcher = updater.dispatcher
import logging

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)


BUTTONS = [['🎵 Audio (MP3)', '🎬 Video (MP4)'], ['📁 Archivo'], ['❌ Cancelar']]
DEFAULT_KEYBOARD = ReplyKeyboardMarkup(BUTTONS, resize_keyboard=True)
URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)
DOWNLOAD_TIMEOUT = 60 * 10
STATE = {}


def start(bot, update):
    name = update.message.chat.first_name
    STATE[update.message.chat_id] = {
        'link': None,
        'mode': None,
        'updated_at': time.time(),
    }
    bot.sendMessage(chat_id=update.message.chat_id,
                    text=("Hola {0}! 👋\n\n"
                          "Soy tu bot para descargar contenidos de enlaces.\n"
                          "Envíame un link y elige el formato.").format(name),
                    reply_markup=DEFAULT_KEYBOARD)
start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)


def help_command(bot, update):
    bot.sendMessage(
        chat_id=update.message.chat_id,
        text=(
            "📌 *Cómo usar el bot*\n\n"
            "1) Envíame un enlace.\n"
            "2) Elige: Audio, Video o Archivo.\n\n"
            "3) Para cancelar una descarga, usa /cancel.\n\n"
            "También puedes usar:\n"
            "`/download <link> [audio|video|file]`\n"
            "`/status` para ver el enlace guardado\n"
            "Ejemplo:\n"
            "`/download https://example.com video`"
        ),
        parse_mode='Markdown',
        reply_markup=DEFAULT_KEYBOARD,
    )

help_handler = CommandHandler('help', help_command)
dispatcher.add_handler(help_handler)


def _get_downloader():
    return yt_dlp if yt_dlp else youtube_dl


def _format_filename(title):
    if ":" in title:
        title = title.replace(":", " -")
    if "?" in title:
        title = title.replace("?", "")
    if "/" in title:
        title = title.replace("/", "_")
    if "|" in title:
        title = title.replace("|", "_")
    if '"' in title:
        title = title.replace('"', "'")
    return title


def _extract_link(text):
    match = URL_RE.search(text or "")
    return match.group(0) if match else None


def _get_state(chat_id):
    state = STATE.get(chat_id)
    if not state:
        state = {'link': None, 'mode': None, 'updated_at': time.time()}
        STATE[chat_id] = state
    return state


def _set_state(chat_id, link=None, mode=None):
    state = _get_state(chat_id)
    if link is not None:
        state['link'] = link
    if mode is not None:
        state['mode'] = mode
    state['updated_at'] = time.time()


def _cleanup_state(chat_id):
    state = _get_state(chat_id)
    if time.time() - state['updated_at'] > DOWNLOAD_TIMEOUT:
        state['link'] = None
        state['mode'] = None


def _send_progress(bot, update, message):
    bot.sendMessage(chat_id=update.message.chat_id, text=message)


def _download_direct_file(link):
    filename = link.split("/")[-1].split("?")[0] or "archivo"
    filename = _format_filename(filename)
    urllib.request.urlretrieve(link, filename)
    return filename


def echo(bot, update):
    name = update.message.chat.first_name
    text = str(update.message.text or "")
    _cleanup_state(update.message.chat_id)
    link = _extract_link(text)
    if link:
        _set_state(update.message.chat_id, link=link)
        bot.sendMessage(
            chat_id=update.message.chat_id,
            text="✅ Link guardado. ¿Qué deseas descargar?",
            reply_markup=DEFAULT_KEYBOARD,
        )
        return

    choice = text.lower()
    if "audio" in choice or "música" in choice or "musica" in choice:
        _set_state(update.message.chat_id, mode="audio")
        _dispatch_download(bot, update, "audio")
    elif "video" in choice or "vídeo" in choice:
        _set_state(update.message.chat_id, mode="video")
        _dispatch_download(bot, update, "video")
    elif "archivo" in choice or "file" in choice or "document" in choice:
        _set_state(update.message.chat_id, mode="file")
        _dispatch_download(bot, update, "file")
    elif "cancelar" in choice or "cancel" in choice:
        cancel(bot, update)
    else:
        bot.sendMessage(
            chat_id=update.message.chat_id,
            text=("Hola {0}! 👋\n"
                  "Envíame un enlace para empezar.").format(name),
            reply_markup=DEFAULT_KEYBOARD,
        )
echo_handler = MessageHandler([Filters.text], echo)
dispatcher.add_handler(echo_handler)


def _dispatch_download(bot, update, mode):
    state = _get_state(update.message.chat_id)
    link = state.get('link')
    if not link:
        bot.sendMessage(
            chat_id=update.message.chat_id,
            text="Primero envíame un enlace para descargar.",
            reply_markup=DEFAULT_KEYBOARD,
        )
        return
    if mode == "audio":
        music(bot, update, link)
    elif mode == "video":
        video(bot, update, link)
    else:
        file_any(bot, update, link)


@run_async
def music(bot, update, link):
    title = ""
    path = ""
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
        _send_progress(bot, update, "⬇️ Descargando audio...")
        downloader = _get_downloader()
        with downloader.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            title = _format_filename(info['title'])
            path = title + '.mp3'
        _send_progress(bot, update, "📤 Enviando audio...")
        bot.sendAudio(chat_id=update.message.chat_id,
                      audio=open(path, 'rb'), title=title)
        _send_progress(bot, update, "✅ ¡Listo!")
        name = update.message.chat.first_name
        print(name + " downloaded " + title)
    except Exception:
        traceback.print_exc()
        bot.sendMessage(chat_id=update.message.chat_id,
                        text="Lo siento, no pude descargar el audio.")
    finally:
        if path and os.path.exists(path):
            os.remove(path)


@run_async
def video(bot, update, link):
    title = ""
    path = ""
    try:
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': '%(title)s.%(ext)s'
        }
        _send_progress(bot, update, "⬇️ Descargando video...")
        downloader = _get_downloader()
        with downloader.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            title = _format_filename(info['title'])
            ext = info.get('ext', 'mp4')
            path = title + '.' + ext
        _send_progress(bot, update, "📤 Enviando video...")
        bot.sendVideo(chat_id=update.message.chat_id,
                      video=open(path, 'rb'), title=title)
        _send_progress(bot, update, "✅ ¡Listo!")
        name = update.message.chat.first_name
        print(name + " downloaded " + title)
    except Exception:
        traceback.print_exc()
        bot.sendMessage(chat_id=update.message.chat_id,
                        text="Lo siento, no pude descargar el video.")
    finally:
        if path and os.path.exists(path):
            os.remove(path)


@run_async
def file_any(bot, update, link):
    title = ""
    path = ""
    try:
        ydl_opts = {
            'format': 'best',
            'outtmpl': '%(title)s.%(ext)s'
        }
        _send_progress(bot, update, "⬇️ Descargando archivo...")
        downloader = _get_downloader()
        with downloader.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            title = _format_filename(info.get('title') or "archivo")
            ext = info.get('ext', 'bin')
            path = title + '.' + ext
        _send_progress(bot, update, "📤 Enviando archivo...")
        bot.sendDocument(chat_id=update.message.chat_id,
                         document=open(path, 'rb'))
        _send_progress(bot, update, "✅ ¡Listo!")
    except Exception:
        try:
            path = _download_direct_file(link)
            _send_progress(bot, update, "📤 Enviando archivo...")
            bot.sendDocument(chat_id=update.message.chat_id,
                             document=open(path, 'rb'))
            _send_progress(bot, update, "✅ ¡Listo!")
        except Exception:
            traceback.print_exc()
            bot.sendMessage(chat_id=update.message.chat_id,
                            text="Lo siento, no pude descargar ese archivo.")
    finally:
        if path and os.path.exists(path):
            os.remove(path)


def download_command(bot, update, args):
    if not args:
        bot.sendMessage(
            chat_id=update.message.chat_id,
            text="Uso: /download <link> [audio|video|file]",
            reply_markup=DEFAULT_KEYBOARD,
        )
        return
    link = _extract_link(" ".join(args))
    if not link:
        bot.sendMessage(chat_id=update.message.chat_id,
                        text="No encontré un enlace válido.",
                        reply_markup=DEFAULT_KEYBOARD)
        return
    _set_state(update.message.chat_id, link=link)
    mode = args[-1].lower()
    if mode in ("audio", "video", "file"):
        _set_state(update.message.chat_id, mode=mode)
        _dispatch_download(bot, update, mode)
    else:
        bot.sendMessage(
            chat_id=update.message.chat_id,
            text="✅ Link guardado. Elige formato.",
            reply_markup=DEFAULT_KEYBOARD,
        )


download_handler = CommandHandler('download', download_command, pass_args=True)
dispatcher.add_handler(download_handler)

def cancel(bot, update):
    _set_state(update.message.chat_id, link=None, mode=None)
    bot.sendMessage(
        chat_id=update.message.chat_id,
        text="❌ Cancelado. Envíame un enlace para empezar de nuevo.",
        reply_markup=DEFAULT_KEYBOARD,
    )


cancel_handler = CommandHandler('cancel', cancel)
dispatcher.add_handler(cancel_handler)


def status(bot, update):
    state = _get_state(update.message.chat_id)
    link = state.get('link')
    mode = state.get('mode')
    if link:
        bot.sendMessage(
            chat_id=update.message.chat_id,
            text="🧾 Estado actual:\nLink: {0}\nModo: {1}".format(link, mode or "sin elegir"),
            reply_markup=DEFAULT_KEYBOARD,
        )
    else:
        bot.sendMessage(
            chat_id=update.message.chat_id,
            text="No tengo un enlace guardado. Envíame uno para empezar.",
            reply_markup=DEFAULT_KEYBOARD,
        )


status_handler = CommandHandler('status', status)
dispatcher.add_handler(status_handler)



def unknown(bot, update):
    bot.sendMessage(chat_id=update.message.chat_id,
                    text="Lo siento, no entendí ese comando.")
unknown_handler = MessageHandler([Filters.command], unknown)
dispatcher.add_handler(unknown_handler)

updater.start_polling()
updater.idle()

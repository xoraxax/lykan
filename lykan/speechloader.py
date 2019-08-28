# Run as "python3 -m lykan.speechloader" to regenerate voice data.

import os
import builtins
builtins._ = lambda x, *args: (x % args) if args else x

from babel.messages.pofile import read_po
from boto3 import Session

from lykan import cards, util, gameengine


TRANSLATIONS_DIR = os.path.join(os.path.abspath(__file__ + "/.."), "translations")

session = Session(profile_name="default")
polly = session.client("polly")


def get_all_raw_messages(locale):
    transfilename = os.path.join(TRANSLATIONS_DIR, locale, "LC_MESSAGES", "messages.po")
    catalog = read_po(open(transfilename, "r"))
    voice_name = None
    for message in catalog:
        if "<Voice>" in message.id:
            voice_name = (message.string or message.id).split("<Voice>", 1)[1].split("</", 1)[0]
    yield (catalog, voice_name) if voice_name else (None, "Unknown")
    for message in catalog:
        txt = message.string or message.id
        if "python-format" in message.flags and "%(" not in txt or message.fuzzy or "<" in txt or \
                any(fname.endswith("j2") for fname, _ in message.locations):
            continue
        yield txt


def get_all_titles(catalog):
    return {catalog[c.TITLE].string or catalog[c.TITLE].id for c in cards.ALL_CARDS + gameengine.Subgroup.__subclasses__() if hasattr(c, "TITLE")}


def get_all_potential_messages(messages_iter, **kwargs):
    for message in messages_iter:
        if "%(" in message:
            groupname = message.split("%(", 1)[1].split(")", 1)[0]
            for value in kwargs[groupname]:
                yield message % {groupname: value}
        else:
            yield message % ()


def create_cache_file(voice, text, directory):
    fname = util.gen_hash(text) + ".mp3"
    path = os.path.join(directory, fname)
    if os.path.exists(path):
        return
    response = polly.synthesize_speech(Text=text, VoiceId=voice, OutputFormat="mp3")
    with open(path, "wb") as f:
        f.write(response.get("AudioStream").read())
    return True


def main():
    for locale in os.listdir(TRANSLATIONS_DIR):
        if not os.path.isdir(os.path.join(TRANSLATIONS_DIR, locale)):
            continue
        voice_dir = os.path.join(TRANSLATIONS_DIR, locale, "voice")
        raw_messages = get_all_raw_messages(locale)
        catalog, voice_name = next(raw_messages)
        for message in get_all_potential_messages(raw_messages, num=range(20), title=get_all_titles(catalog)):
            if create_cache_file(voice_name, message, voice_dir):
                print("Generated", message)
            else:
                print("Reused", message)


if __name__ == '__main__':
    main()

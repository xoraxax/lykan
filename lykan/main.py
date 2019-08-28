import gevent.monkey
gevent.monkey.patch_all()

import builtins
import itertools
import json
import logging
import os
import queue
import random
import sys
import threading
import time

from flask import Flask, render_template, g, redirect, url_for, send_from_directory
from flask_babel import Babel, gettext, ngettext
from flask_sockets import Sockets
builtins._ = lambda x, *args, **kwargs: gettext(x) % (args or kwargs)

from lykan import gameengine, util, cards

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)
app = Flask(__name__)
babel = Babel(app)
sockets = Sockets(app)
app.games = {}


VOICE = _("<Voice>Brian</Voice>")
_TRANSLATIONS_DIR = os.path.join(os.path.abspath(__file__ + "/.."), "translations")
KNOWN_LANGS = ["en"] + [lang for lang in os.listdir(_TRANSLATIONS_DIR)
                        if os.path.exists(os.path.join(_TRANSLATIONS_DIR, lang, "voice")) and lang != "en"]


@babel.localeselector
def get_locale():
    return getattr(g, "current_locale", "en")


class AlreadyPlaying(Exception):
    pass


class Basics(gameengine.Request):
    def __init__(self, player, card_title):
        self.player = player
        self.card_title = card_title


class UI:
    def __init__(self, game, player):
        self.gen = game.get_player_generator(player)
        self.transform_reply = None

    def __iter__(self):
        return self

    def __next__(self):
        return self.send(None)

    def send(self, reply):
        if self.transform_reply:
            reply = self.transform_reply(reply)
        req = self.gen.send(reply)
        ws_req, transform_reply = getattr(self, type(req).__name__)(req)
        self.transform_reply = transform_reply
        return ws_req


class WSUI(UI):
    def Basics(self, req):
        return dict(ask="setup", player=req.player.name if req.player else None, card_title=req.card_title), None

    def InfoMessage(self, req):
        msg = make_msg(req.msg, temporary=req.temporary)
        msg["players"] = [p.name for p in req.players or []]
        if not req.player:
            msg["hash"] = util.gen_hash(req.msg)
        if req.vote:
            msg["vote"] = {p.name: v.name for p, v in req.vote.items()}
        return msg, None

    def SelectNPlayers(self, req):
        def transform_reply(reply):
            return list(filter(None, [req.game.players_by_name.get(p_name, None) for p_name in json.loads(reply)]))
        return dict(ask="n", n=req.n, amongst=[p.name for p in (req.amongst or req.game.players_alive)], prompt=req.prompt), transform_reply

    def Select1Player(self, req):
        return self.SelectNPlayers(req)

    def YesNoQuestion(self, req):
        def transform_reply(reply):
            return reply == "t"
        return dict(ask="yesno", prompt=req.prompt, players=[p.name for p in req.players or []]), transform_reply

    def EverybodySelect1Player(self, req):
        return self.SelectNPlayers(req)


class ThreadedGame(gameengine.Game, threading.Thread):
    def __init__(self, locale, code):
        gameengine.Game.__init__(self)
        threading.Thread.__init__(self)
        self.locale = locale
        self.code = code
        self.lock = threading.Lock()
        self.game_start = threading.Event()
        self.join_events = queue.Queue()
        self.nonce = None
        self.pipe_parent, self.pipe_child = util.Pipe()
        self.last_req = None

    def add_player(self, name):
        with self.lock:
            if self.game_start.is_set():
                raise AlreadyPlaying
            parent_side, child_side = util.Pipe()
            player = super().add_player(name)
            player.last_req = None
            player.pipe_child = child_side
            player.pipe_parent = parent_side
            self.join_events.put(None)
            return player

    def get_player_generator(self, player):
        yield from self.gen_basics_for_player(player)  # First time.
        if player:
            yield gameengine.InfoMessage(_("Waiting for game master to start the game."), player=player, temporary=True)
        yield from self._convert_player_pipe(player)

    def _convert_player_pipe(self, player):
        if player is None:
            player = self
        resume = player.last_req
        pipe = player.pipe_child
        while True:
            try:
                if resume and hasattr(resume, "game"):
                    req = resume
                else:
                    req = pipe.recv()
                    req.game = self
                resume = False
                if player is self:
                    time.sleep(4)
                pipe.send((yield req))
            except StopIteration:
                break

    def gen_basics_for_player(self, player):
        if player:
            yield Basics(player=player, card_title=(_(player.role_card.TITLE) if player.role_card else None))  # XXX add description/image
        else:
            yield Basics(player=None, card_title=None)

    def play_game(self):
        for player in self.players:
            yield from self.gen_basics_for_player(player)  # Second time.
        yield from super().play_game()

    def run(self):
        with app.app_context():
            activate_locale(self.locale)
            self._run()
        del app.games[self.code]

    def _run(self):
        self.game_start.wait()
        gen = self.play_game()
        reply = None
        while True:
            try:
                req = gen.send(reply)
                if req.player is None:
                    if isinstance(req, gameengine.EverybodySelect1Player):
                        for player in self.players_alive:
                            player.last_req = req
                            player.pipe_parent.send(req)
                        votes = {}
                        for player in self.players_alive:
                            votee = player.pipe_parent.recv()
                            votes[player] = req.coerce(votee)
                        reply = votes
                    elif isinstance(req, gameengine.InfoMessage):
                        self.last_req = req
                        self.pipe_parent.send(req)
                        self.pipe_parent.recv()
                        reply = None
                    else:
                        assert False, "Unsupported request"
                else:
                    req.player.last_req = req
                    while True:
                        req.player.pipe_parent.send(req)
                        reply = req.player.pipe_parent.recv()
                        if isinstance(req, gameengine.SelectNPlayers):
                            if len(reply) == req.n:
                                break
                            else:
                                error = gameengine.InfoMessage(_("Please select the correct amount of players."), req.player)
                                req.player.pipe_parent.send(error)
                                req.player.pipe_parent.recv()
                        else:
                            break
                    reply = req.coerce(reply)
            except gameengine.GameEnd:
                break


def make_msg(msg, temporary=False):
    return dict(ask=None, content=msg, temporary=temporary)


def _check_game(game):
    if game is None:
        yield make_msg(_("<b>Game not found! Check the address you entered!</b>"))
        return False
    activate_locale(game.locale)
    return True


def mobile_client(game):
    if not (yield from _check_game(game)):
        return
    session = game.retrieve_session((yield dict(ask="nonce")))
    try:
        while session.player is None:
            if game.game_start.is_set():
                raise AlreadyPlaying
            name = yield dict(ask="string", prompt=_("<b>What is your name?</b>"))
            try:
                session.activate(name)
            except gameengine.NameClash:
                yield make_msg(_("Name already taken! Try again."))
    except AlreadyPlaying:
        yield make_msg(_("Game has already started."))
        return
    yield from WSUI(game, session.player)


def master_client(game):
    if not (yield from _check_game(game)):
        return
    nonce = (yield dict(ask="nonce"))
    if game.nonce is None:
        game.nonce = nonce
    elif game.nonce != nonce:
        yield make_msg(_("You do not have access to this game."))
        return
    if not game.game_start.is_set():
        if game.players:
            yield dict(ask="showplayers", players=sorted(player.name for player in game.players))
        else:
            yield make_msg(_("Waiting for players to join the game."), temporary=True)
        while True:
            try:
                if game.join_events.get(timeout=0.1):
                    yield make_msg(_("%(num)i players are participating.", num=len(game.players)))
                    break
                else:
                    yield dict(ask="showplayers", players=sorted(player.name for player in game.players))
            except queue.Empty:
                pass
        while True:
            selected_cards = json.loads((yield dict(ask="cards", available={cls.__name__: dict(title=_(cls.TITLE)) for cls in sorted(cards.ALL_CARDS, key=lambda c: c.__name__)})))
            try:
                game.prepare(itertools.chain(*[[getattr(cards, card_name)] * count for card_name, count in selected_cards.items()]))
            except gameengine.ValidationFailed as exc:
                yield make_msg(exc.args[0])
            else:
                break
        with game.lock:
            game.game_start.set()
    yield from WSUI(game, None)


def run_client_on_ws(client, ws):
    reply = None
    while not ws.closed:
        try:
            msg = client.send(reply)
            ws.send(json.dumps(msg))
            reply = ws.receive()
            if reply is None:  # WS closed
                break
        except StopIteration:
            break

def make_ws_endpoint(ws, client_func):
    code = ws.receive()
    game = app.games.get(code)
    client = client_func(game)
    run_client_on_ws(client, ws)

@sockets.route('/mobilews')
def mobilews(ws):
    make_ws_endpoint(ws, mobile_client)


@sockets.route('/masterws')
def masterws(ws):
    make_ws_endpoint(ws, master_client)


@app.route('/')
def root():
    return render_template("main.html.j2", locale="en")


@app.route('/js/<locale>')
def js(locale):
    activate_locale(locale)
    return render_template("lykan.js.j2", locale=locale)


@app.route("/voice/<locale>/<hash>")
def voice(locale, hash):
    return send_from_directory(os.path.join(os.path.abspath(__file__ + "/.."), "translations", locale, "voice"), hash + ".mp3", cache_timeout=600)


@app.route("/create_new_game/<locale>", methods=["POST"])
def create_new_game(locale):
    assert locale in KNOWN_LANGS
    code = "".join(random.choice("ABCDEFGHJKMNPQRSTUVWXYZ") for i in range(5))
    app.games[code] = game = ThreadedGame(locale, code)
    game.start()
    return redirect(url_for("game_masterscreen", code=code))


@app.route("/start_game/<code>/<nonce>")
def start_game(code, nonce):
    game = app.games[code]
    if nonce != game.nonce:
        return "Nonce error"
    game.join_events.put(True)
    return "OK"


def activate_locale(locale):
    assert locale in KNOWN_LANGS
    g.current_locale = locale

def render_screen(funcname, tmpl, code):
    code2 = code.strip().upper()
    if code2 not in app.games:
        return "<b>Invalid code, check the address you entered!</b>"
    if code2 != code:
        return redirect(url_for(funcname, code=code2))
    activate_locale(app.games[code2].locale)
    return render_template(tmpl, code=code2, locale=get_locale())

@app.route("/master/<code>")
def game_masterscreen(code):
    return render_screen("game_masterscreen", "game.html.j2", code)

@app.route("/<code>")
def game(code):
    return render_screen("game", "mobile.html.j2", code)


if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = pywsgi.WSGIServer(('', port), app, handler_class=WebSocketHandler)
    logging.info("Werewolves started")
    logging.info("Serving on port %i", port)
    server.serve_forever()

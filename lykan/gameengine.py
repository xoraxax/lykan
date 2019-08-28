import collections
import random

from lykan import util


GROUP_SUBGROUP, GROUP_SINGLE = range(2)


class GameEnd(Exception):
    pass


class ValidationFailed(Exception):
    pass

class NameClash(Exception):
    pass

class AllDead(Exception):
    pass


def compute_key(card, reduce_kind):
    if reduce_kind is GROUP_SUBGROUP:
        return [x for x in type(card).mro() if issubclass(x, Subgroup)][0]
    elif reduce_kind == GROUP_SINGLE:
        return card
    else:
        raise NotImplementedError


class Request:
    def __init__(self, player):
        self.player = player

    def coerce(self, value):
        return value


class SelectNPlayers(Request):
    def __init__(self, player, n, prompt, amongst=None):
        assert player is not None
        if player is Ellipsis:
            player = None
        super().__init__(player)
        self.n = n
        self.prompt = prompt
        self.amongst = amongst


class Select1Player(SelectNPlayers):
    def __init__(self, player, prompt, amongst=None):
        super().__init__(player, 1, prompt, amongst)

    def coerce(self, value):
        return value[0] if value else None


class EverybodySelect1Player(Select1Player):
    def __init__(self, prompt, amongst=None):
        super().__init__(Ellipsis, prompt, amongst)


class YesNoQuestion(Request):
    def __init__(self, player, prompt, players=None):
        assert player is not None
        super().__init__(player)
        self.prompt = prompt
        self.players = players
        
    
class InfoMessage(Request):
    def __init__(self, msg_or_msgs, player=None, players=None, vote=None, temporary=False, vibrate=True, fast=False):
        super().__init__(player)
        self.msg = random.choice(msg_or_msgs) if isinstance(msg_or_msgs, list) else msg_or_msgs
        self.players = players
        self.vote = vote
        self.temporary = temporary
        self.vibrate = vibrate
        self.fast = fast


class Player:
    def __init__(self, game, name):
        self.game = game
        self.name = name
        self.role_card = None
        self.is_alive = True

    def assign_role(self, card_cls):
        self.role_card = card_cls(self)

    def kill(self):
        is_dead = (yield from self.role_card.kill())
        if is_dead:
            yield InfoMessage(_("You have died."), player=self)
        return is_dead


class Session:
    def __init__(self, game):
        self.game = game
        self.player = None

    def activate(self, name):
        assert not self.player
        self.player = self.game.add_player(name)


class Game:
    def __init__(self):
        self.players = []
        self.players_by_name = {}
        self.sessions = {}
        self.hitlist = None

    def retrieve_session(self, nonce):
        return self.sessions.setdefault(nonce, Session(self))

    @property
    def players_alive(self):
        return [player for player in self.players if player.is_alive]

    def add_player(self, name):
        if name in self.players_by_name:
            raise NameClash
        player = Player(self, name)
        self.players.append(player)
        self.players_by_name[name] = player
        return player

    def _play_night(self, is_first_night):
        self.hitlist = []
        yield InfoMessage(_("The night begins! Everybody closes their eyes."))
        for cards in util.toposort(self.players):
            reducers = collections.defaultdict(list)
            eye_openees = collections.defaultdict(list)
            for card in cards:
                if hasattr(card, "prepare") and is_first_night:
                    eye_openees[card].append(card)
                if card.EYES_OPEN is not None:
                    key = compute_key(card, card.EYES_OPEN)
                    eye_openees[key].append(card)
            for key in eye_openees:
                yield InfoMessage(_("%(title)s opens their eyes.", title=_(key.TITLE)))
                for card in eye_openees[key]:
                    if hasattr(card, "prepare"):
                        yield from card.prepare()
                    do_reduce = yield from card.run_at_night()
                    if do_reduce:
                        reducers[key].append(card)
                yield InfoMessage(_("%(title)s closes their eyes again.", title=_(key.TITLE)))
            for reduce_key in reducers.keys():
                for card in reducers[reduce_key]:
                    yield from card.reduce(reducers[reduce_key])
        yield InfoMessage(_("Everybody opens their eyes again."))
                
    def _play_day(self, day_no):
        yield InfoMessage(_("Day %(num)i begins!", num=day_no), fast=True)
        died = False
        for player in self.hitlist:
            died |= yield from player.kill()
        if not died:
            yield InfoMessage(_("Last night, nobody died."))
        self.hitlist = None
        yield from self._check_winning_condition()
        while True:
            yield InfoMessage(_("Discuss, dear village."))
            vote = yield EverybodySelect1Player(_("Who should the village kill?"))
            yield InfoMessage(_("And the vote cast was:"), vote=vote)
            victim = util.check_vote(self.players_alive, vote)
            if victim:
                died = yield from victim.kill()
                if not died:
                    yield InfoMessage(_("The person did not die!"))
                break
            else:
                yield InfoMessage(_("No conclusive vote was cast."))
        yield from self._check_winning_condition()

    def _check_winning_condition(self):
        try:
            winner = self.who_has_won()
        except AllDead:
            yield InfoMessage(_("The game has ended, all are dead."))
            raise GameEnd
        if winner:
            winners = winner.materialize(self)
            yield InfoMessage(_("The game has ended. The winners are: %(title)s.", title=_(winner.TITLE)), players=winners)
            for winner in winners:
                yield InfoMessage(_("You have won!"), player=winner)
            raise GameEnd

    def play_game(self):
        self._validate()
        yield InfoMessage(_("Welcome to Werewolves!"), fast=True)
        day = 0
        while True:
            yield from self._play_night(is_first_night=not day)
            day += 1
            yield from self._play_day(day)

    def run_with_ui(self, ui):
        gen = self._play_game()
        reply = None
        while True:
            try:
                req = gen.send(reply)
                reply = ui.handle(self, req)
            except StopIteration:
                break

    def who_has_won(self):
        if not self.players_alive:
            raise AllDead 
        for cls in Subgroup.__subclasses__():
            if cls.has_won(self):
                return cls.compute_winner(self)

    def _validate(self):
        for cls in Subgroup.__subclasses__():
            cls.validate(self)

    def prepare(self, iter_card_classes):
        card_classes = list(iter_card_classes)
        if not len(card_classes) == len(self.players):
            raise ValidationFailed(_("Not the correct amount of cards"))
        random.shuffle(card_classes)
        for player, card in zip(self.players, card_classes):
            player.assign_role(card)


class Subgroup:
    @classmethod
    def has_won(cls, game):
        return all(isinstance(player.role_card, cls) for player in game.players_alive)

    @classmethod
    def compute_winner(cls, game):
        return cls

    @classmethod
    def validate(cls, game):
        pass

    @classmethod
    def materialize(cls, game):
        """Computes the winning members of this group."""
        return [player for player in game.players_alive if isinstance(player.role_card, cls)]

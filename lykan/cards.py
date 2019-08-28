import itertools

from lykan import gameengine, util

CAN_KILL_AT_NIGHT, = range(1)


def _empty_generator_method(self):
    # We have joy, we have fun, we have PEP 479.
    return
    yield


class RoleCard:
    TAGS = []
    RUNS_AFTER = []
    EYES_OPEN = None

    def __init__(self, player):
        self.player = player
        self.after_death_triggers = []

    run_at_night = _empty_generator_method

    def after_death(self):
        for method in self.after_death_triggers:
            yield from method()

    def kill(self):
        assert self.player.is_alive
        self.player.is_alive = False
        yield gameengine.InfoMessage(_("This player died:"), players=[self.player])
        yield gameengine.InfoMessage(_("The role was %(title)s.", title=_(self.player.role_card.TITLE)), fast=True)
        yield from self.after_death()
        return True


class Citizens(gameengine.Subgroup):
    TITLE = _("The team of Citizens")

class Werewolves(gameengine.Subgroup):
    TITLE = _("The team of Werewolves")


class InstanceMorphMeta(type):
    """Delegates isinstance check to the classmethod isinstance."""
    def __instancecheck__(self, instance):
        return self.isinstance(instance)


class LovingCouple(gameengine.Subgroup, metaclass=InstanceMorphMeta):
    TITLE = _("The loving couple")

    @classmethod
    def isinstance(self, obj):
        return getattr(obj, 'is_in_love', False)

    @classmethod
    def make_in_love(self, player):
        player.role_card.is_in_love = True


class SingletonWinnerSubgroup(gameengine.Subgroup):
    @classmethod
    def has_won(cls, game):
        return all(not player.is_alive for player in game.players if isinstance(player.role_card, cls))

    @classmethod
    def compute_winner(cls, game):
        winners = [player.role_card for player in game.players if isinstance(player.role_card, cls)]
        if winners:
            return winners[0]

    def materialize(self, game):
        return [self.player]

    @classmethod
    def validate(cls, game):
        if len([1 for player in game.players if isinstance(player.role_card, cls)]) > 1:
            raise gameengine.ValidationFailed(_("Too many cards of singleton type %s", cls.TITLE))


class CitizensActiveAtNight(Citizens):
    EYES_OPEN = gameengine.GROUP_SINGLE


class Witch(CitizensActiveAtNight, RoleCard):
    TITLE = _("The witch")
    RUNS_AFTER = [CAN_KILL_AT_NIGHT]
    TAGS = [CAN_KILL_AT_NIGHT]

    def __init__(self, player):
        super().__init__(player)
        self.has_healing_potion = True
        self.has_killing_potion = True

    def run_at_night(self):
        game = self.player.game
        if self.has_healing_potion and game.hitlist:
            if (yield gameengine.YesNoQuestion(self.player, _("Do you want to use your healing potion?"), players=game.hitlist)):
                if len(game.hitlist) == 1:
                    game.hitlist.clear()
                else:
                    saved_player = (yield gameengine.Select1Player(self.player, _("Who do you want to heal?"), game.hitlist))
                    game.hitlist.remove(saved_player)
                self.has_healing_potion = False
        if self.has_killing_potion:
            if (yield gameengine.YesNoQuestion(self.player, _("Do you want to use your killing potion?"))):
                killed_player = (yield gameengine.Select1Player(self.player, _("Who do you want to kill?")))
                if killed_player not in game.hitlist:
                    game.hitlist.append(killed_player)
                self.has_killing_potion = False


class Werewolve(Werewolves, RoleCard):
    TAGS = [CAN_KILL_AT_NIGHT]
    EYES_OPEN = gameengine.GROUP_SUBGROUP

    def run_at_night(self):
        self.to_kill = (yield gameengine.Select1Player(self.player, _("Who do you want to kill, werewolve? The majority vote will win.")))
        return True
    
    def reduce(self, other_cards):
        game = self.player.game
        poll = {card: card.to_kill for card in other_cards}
        votee = util.check_vote(game.players_alive, poll)
        if votee:
            yield gameengine.InfoMessage(_("You werewolves chose to kill this player:"), players=[votee], player=self.player)
        if votee and votee not in game.hitlist:
            game.hitlist.append(self.to_kill)


class Citizen(Citizens, RoleCard):
    pass


class Hunter(Citizens, RoleCard):
    TITLE = _("The hunter")
    def after_death(self):
        yield from super().after_death()
        yield gameengine.InfoMessage(_("And the hunter produced a shot ..."))
        yield from (yield gameengine.Select1Player(self.player, _("Who do you want to shoot?"))).kill()


class Lynchee(SingletonWinnerSubgroup, RoleCard):
    TITLE = _("The lynchee")


class Cupid(Citizens, RoleCard):
    TITLE = _("The cupid")

    def prepare(self):
        couple = (yield gameengine.SelectNPlayers(self.player, 2, _("Who should fall in love?")))
        for first, second in itertools.permutations(couple):
            LovingCouple.make_in_love(first)
            def make_trigger(to_kill):
                def trigger():
                    if to_kill.is_alive:
                        yield gameengine.InfoMessage(_("Thus with a kiss you die!"))
                        yield from to_kill.kill()
                return trigger
            first.role_card.after_death_triggers.append(make_trigger(second))
            yield gameengine.InfoMessage(_("You fell in love with this player. Be sure to survive both!"), player=first,
                                         players=[second], vibrate=False)


class Seer(CitizensActiveAtNight, RoleCard):
    TITLE = _("The seer")
    def run_at_night(self):
        player = yield gameengine.Select1Player(self.player, _("Whose role do you want to inquire?"))
        yield gameengine.InfoMessage(_("This player has the role '%(title)s'.", title=_(player.role_card.TITLE)), player=self.player, players=[player])


class Prince(Citizens, RoleCard):
    TITLE = _("The prince")
    def __init__(self, *args):
        super().__init__(*args)
        self.killing_attempt_happened = False

    def kill(self):
        if self.killing_attempt_happened:
            return (yield from super().kill())
        else:
            self.killing_attempt_happened = True
            return False

ALL_CARDS = RoleCard.__subclasses__()

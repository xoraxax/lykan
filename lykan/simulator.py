import builtins
builtins._ = lambda x, *args: (x % args) if args else x
from lykan import cards, gameengine


class TestUI:
    def handle(self, game, req):
        if isinstance(req, gameengine.InfoMessage):
            print(((req.player.name + ": ") if req.player else "") + req.msg + " ")
            if req.players:
                print(", ".join(p.name for p in req.players))
            if req.vote:
                for voter, votee in req.vote.items():
                    print("%s voted for %s" % (voter.name, votee.name))
            return
        elif isinstance(req, gameengine.SelectNPlayers):
            players = req.amongst or game.players_alive
            for i, player in enumerate(p for p in players):
                if player.is_alive:
                    print(i, player.name)
            return req.coerce([players[int(x)] for x in input(req.player.name + ": " + "%s (select %i): " % (req.prompt, req.n,)).split()][:req.n])
        elif isinstance(req, gameengine.EverybodySelect1Player):
            players = req.amongst or game.players_alive
            for i, player in enumerate(p for p in players):
                if player.is_alive:
                    print(i, player.name)
            votes = {}
            for player in players:
                print("Dear %s" % player.name)
                val = req.coerce([players[int(x)] for x in input("%s: " % (req.prompt,)).split()][0])
                votes[player] = val
            return votes
        elif isinstance(req, gameengine.YesNoQuestion):
            if req.players:
                print(", ".join(p.name for p in req.players))
            return input(((req.player.name + ": ") if req.player else "") + req.prompt + " [y/N]? ").lower() == "y"
        else:
            1/0


if __name__ == '__main__':
    ui = TestUI()
    game = gameengine.Game()
    game.add_player("Brian").assign_role(cards.Witch)
    game.add_player("Mallory").assign_role(cards.Citizen)
    game.add_player("Eve").assign_role(cards.Werewolve)
    game.add_player("Ada").assign_role(cards.Werewolve)
    game.add_player("Helmut").assign_role(cards.Hunter)
    game.add_player("Larry").assign_role(cards.Lynchee)
    game.add_player("Charlie").assign_role(cards.Cupid)
    game.add_player("Susan").assign_role(cards.Seer)
    game.add_player("Barack").assign_role(cards.Prince)
    try:
        game.run_with_ui(ui)
    except gameengine.GameEnd:
        print("Regular end. EOF.")

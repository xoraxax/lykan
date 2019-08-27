class Game:
    def __init__(self):
        self.players = []

    def add_player(self, name):
        self.players.append(Player(name))


class Player:
    def __init__(self, name):
        self.name = name




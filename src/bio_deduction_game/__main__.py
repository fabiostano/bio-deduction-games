from .data import MockProvider
from .ui import build_app


def main() -> None:
    players = [
        "Hub1 • Player A",
        "Hub1 • Player B",
        "Hub1 • Player C",
        "Hub2 • Player A",
        "Hub2 • Player B",
        "Hub2 • Player C",
    ]
    provider = MockProvider(players)
    app = build_app(provider, players)
    app.exec()


if __name__ == "__main__":
    main()

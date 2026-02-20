from .ui import build_app


def main() -> None:
    app = build_app()
    app.exec()


if __name__ == "__main__":
    main()

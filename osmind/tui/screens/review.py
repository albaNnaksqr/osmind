from textual.screen import Screen
from textual.widgets import Label

class ReviewScreen(Screen):
    def compose(self):
        yield Label("Review — coming soon")

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Title:
    title: str
    level: int


Content = str
TitleOrContent = Title | Content


@dataclass(frozen=True)
class PartSlides:
    title: str | None
    sections: list[TitleOrContent] = field(default_factory=list)

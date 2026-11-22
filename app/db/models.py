"""Модели данных, см. docs/SPEC.md, раздел 4.

Период анкеты хранится как номер месяца программы (1, 2, …); подпись месяца
вычисляется по дате начала программы.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

ROLES = ("hr", "lead", "mentor", "intern")
SIDES = ("intern", "mentor")


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Program(Base):
    __tablename__ = "programs"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    months: Mapped[int] = mapped_column(Integer, default=6)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    program_id: Mapped[int | None] = mapped_column(ForeignKey("programs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str | None] = mapped_column(String(50))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    program_id: Mapped[int | None] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("program_id", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(50))
    side: Mapped[str] = mapped_column(String(10))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    department: Mapped[str | None] = mapped_column(String(200))


class Pair(Base):
    __tablename__ = "pairs"
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    intern_participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"))
    mentor_participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"))
    start_period: Mapped[int] = mapped_column(Integer, default=1)
    end_period: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")
    outcome: Mapped[str | None] = mapped_column(String(20))

    intern: Mapped[Participant] = relationship(foreign_keys=[intern_participant_id], lazy="joined")
    mentor: Mapped[Participant] = relationship(foreign_keys=[mentor_participant_id], lazy="joined")


class PairMentorHistory(Base):
    __tablename__ = "pair_mentor_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id", ondelete="CASCADE"), index=True)
    old_mentor_id: Mapped[int | None] = mapped_column(ForeignKey("participants.id", ondelete="SET NULL"))
    new_mentor_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"))
    period: Mapped[int] = mapped_column(Integer)
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))


class Questionnaire(Base):
    __tablename__ = "questionnaires"
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    side: Mapped[str] = mapped_column(String(10))
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(20), default="builder")
    title: Mapped[str] = mapped_column(String(300), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    questions: Mapped[list["Question"]] = relationship(
        back_populates="questionnaire", order_by="Question.order", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    questionnaire_id: Mapped[int] = mapped_column(
        ForeignKey("questionnaires.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    qtype: Mapped[str] = mapped_column(String(10), default="scale")
    scale_min: Mapped[float | None] = mapped_column(Float)
    scale_max: Mapped[float | None] = mapped_column(Float)
    scale_labels: Mapped[list | None] = mapped_column(JSON)
    options: Mapped[list | None] = mapped_column(JSON)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    mirror_question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"))
    inverse: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    column_key: Mapped[str | None] = mapped_column(String(300))

    questionnaire: Mapped[Questionnaire] = relationship(back_populates="questions")
    topic: Mapped[Topic | None] = relationship(lazy="joined")


class Response(Base):
    __tablename__ = "responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"), index=True)
    questionnaire_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaires.id", ondelete="SET NULL"))
    period: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(20), default="import")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    complete: Mapped[bool] = mapped_column(Boolean, default=True)

    answers: Mapped[list["Answer"]] = relationship(back_populates="response", cascade="all, delete-orphan")
    participant: Mapped[Participant] = relationship(lazy="joined")


class Answer(Base):
    __tablename__ = "answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("responses.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"))
    value_raw: Mapped[str | None] = mapped_column(String(300))
    value_norm: Mapped[float | None] = mapped_column(Float)
    text: Mapped[str | None] = mapped_column(Text)

    response: Mapped[Response] = relationship(back_populates="answers")
    question: Mapped[Question | None] = relationship(lazy="joined")


class CommentAnalysis(Base):
    __tablename__ = "comment_analysis"
    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("answers.id", ondelete="CASCADE"), index=True)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    tone: Mapped[float] = mapped_column(Float, default=0.0)
    anxiety: Mapped[float] = mapped_column(Float, default=0.0)
    contradiction: Mapped[float] = mapped_column(Float, default=0.0)
    quote: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(80), default="rules")
    fallback: Mapped[bool] = mapped_column(Boolean, default=True)


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int | None] = mapped_column(ForeignKey("pairs.id", ondelete="CASCADE"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    period: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(20))
    topic: Mapped[str | None] = mapped_column(String(40))
    strength: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(Text, default="")
    cause: Mapped[str] = mapped_column(Text, default="")
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    verdict: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HealthSnapshot(Base):
    __tablename__ = "health_snapshots"
    __table_args__ = (UniqueConstraint("pair_id", "period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id", ondelete="CASCADE"), index=True)
    period: Mapped[int] = mapped_column(Integer)
    index: Mapped[int] = mapped_column(Integer)
    penalties: Mapped[dict] = mapped_column(JSON, default=dict)


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="assigned")
    period: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    outcomes_text: Mapped[str | None] = mapped_column(Text)
    agreements: Mapped[list | None] = mapped_column(JSON)
    agenda: Mapped[list | None] = mapped_column(JSON)
    effect: Mapped[dict | None] = mapped_column(JSON)


class HrNote(Base):
    __tablename__ = "hr_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TalkRequest(Base):
    __tablename__ = "talk_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    participant_id: Mapped[int | None] = mapped_column(ForeignKey("participants.id", ondelete="SET NULL"))
    topic: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text, default="")
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ImportJob(Base):
    __tablename__ = "import_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"))
    files: Mapped[list] = mapped_column(JSON, default=list)
    schema: Mapped[dict] = mapped_column(JSON, default=dict)
    quality: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MappingProfile(Base):
    __tablename__ = "mapping_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    signature: Mapped[str] = mapped_column(String(64), index=True)
    schema: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AppSetting(Base):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("organization_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[dict | list | float | int | str | bool | None] = mapped_column(JSON)


class DashboardLayout(Base):
    __tablename__ = "dashboard_layouts"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    layout: Mapped[dict] = mapped_column(JSON, default=dict)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    sub: Mapped[str] = mapped_column(String(300), default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    level: Mapped[str] = mapped_column(String(20), default="info")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="Курс")
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    topic: Mapped[str | None] = mapped_column(String(40))
    audience: Mapped[str] = mapped_column(String(10), default="intern")
    duration: Mapped[str] = mapped_column(String(40), default="")
    file_name: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Test(Base):
    __tablename__ = "tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    generated_by: Mapped[str] = mapped_column(String(80), default="rules")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    questions: Mapped[list["TestQuestion"]] = relationship(
        order_by="TestQuestion.id", cascade="all, delete-orphan"
    )


class TestQuestion(Base):
    __tablename__ = "test_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, default=list)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    test_id: Mapped[int | None] = mapped_column(ForeignKey("tests.id", ondelete="CASCADE"))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float | None] = mapped_column(Float)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

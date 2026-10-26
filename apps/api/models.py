from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

TaskType = Literal['manager', 'lecture', 'practice', 'exam', 'project']


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class CourseCreate(InputModel):
    title: str = Field(min_length=1, max_length=120)
    syllabus: str = Field(default='', max_length=30000)


class Course(CourseCreate):
    id: str
    created_at: str


class ExamParameter(InputModel):
    question_type: Literal['single_choice', 'short_answer', 'open_answer']
    count: int = Field(ge=1, le=20)


class RosterEntry(InputModel):
    student_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=80)
    github_id: str = Field(pattern=r'^[a-zA-Z0-9-]{1,39}$')
    repo_name: str = Field(pattern=r'^[a-zA-Z0-9_.-]{1,100}$')


class RunCreate(InputModel):
    task_type: TaskType
    topic: str = Field(min_length=1, max_length=200)
    week: int = Field(default=1, ge=1, le=52)
    guidelines: str = Field(default='', max_length=10000)
    rubric_guidelines: str = Field(default='', max_length=10000)
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    parameters: list[ExamParameter] = Field(default_factory=lambda: [ExamParameter(question_type='short_answer', count=3)], max_length=3)
    roster: list[RosterEntry] = Field(default_factory=list, max_length=20)
    execute_notebook: bool = False
    max_iterations: int = Field(default=3, ge=1, le=5)

    @model_validator(mode='after')
    def unique_ids(self):
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError('Duplicate document IDs')
        if len({r.student_id for r in self.roster}) != len(self.roster):
            raise ValueError('Duplicate roster IDs')
        return self


class Citation(BaseModel):
    document_id: str
    filename: str
    page: int
    text: str


class Document(BaseModel):
    id: str
    course_id: str
    filename: str
    size: int
    status: Literal['ready'] = 'ready'
    pages: int


class Run(BaseModel):
    id: str
    course_id: str
    task_type: TaskType
    topic: str
    status: Literal['queued', 'running', 'waiting_review', 'succeeded', 'failed', 'cancelled']
    revision: int
    mode: Literal['demo', 'real']
    draft: dict | None = None
    citations: list[Citation] = Field(default_factory=list)
    output: str | None = None
    output_format: str = 'md'
    error: str | None = None
    created_at: str
    reviews: list[dict] = Field(default_factory=list)
    child_ids: list[str] = Field(default_factory=list)


class ReviewCreate(InputModel):
    decision: Literal['approve', 'revise']
    expected_revision: int = Field(ge=1)
    feedback: str = Field(default='', max_length=10000)

    @model_validator(mode='after')
    def feedback_required(self):
        if self.decision == 'revise' and not self.feedback:
            raise ValueError('수정 요청 내용을 입력하세요.')
        return self


class DraftUpdate(InputModel):
    expected_revision: int = Field(ge=1)
    draft: dict


class FeedbackCreate(InputModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default='', max_length=2000)


class Error(BaseModel):
    code: str
    message: str
    request_id: str

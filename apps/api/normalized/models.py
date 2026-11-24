from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Input(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class CourseInput(Input):
    title:str=Field(min_length=1,max_length=120)
    syllabus:str=Field(default='',max_length=30000)
class WeekInput(Input):
    weekNumber:int=Field(ge=1,le=52)
    topic:str=Field(min_length=1,max_length=200)
    objectives:str=Field(default='',max_length=3000)
    content:str=Field(default='',max_length=10000)
class PlanInput(Input):
    goals:str=Field(default='',max_length=10000)
    mainTextbooks:str=Field(default='',max_length=10000)
    supplementaryTextbooks:str=Field(default='',max_length=10000)
    expectedRevision:int|None=Field(default=None,ge=0)
    syllabusVersionId:UUID|None=None
    weeks:list[WeekInput]=Field(max_length=52)
    @model_validator(mode='after')
    def unique(self):
        if len({w.weekNumber for w in self.weeks})!=len(self.weeks):raise ValueError('Duplicate week')
        return self
class LinkInput(Input):
    documentId:UUID
    weekNumbers:list[int]=Field(default_factory=list,max_length=52)
class WeeksInput(Input):
    weekNumbers:list[int]=Field(max_length=52)
class SearchInput(Input):
    query:str=Field(min_length=1,max_length=500)
    documentIds:list[UUID]=Field(default_factory=list,max_length=50)
    weekNumbers:list[int]=Field(default_factory=list,max_length=52)
    limit:int=Field(default=12,ge=1,le=24)
class StudentInput(Input):
    studentNumber:str=Field(min_length=1,max_length=64)
    name:str=Field(min_length=1,max_length=120)
    githubId:str|None=Field(default=None,pattern=r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}$')
    repositoryUrl:str|None=Field(default=None,pattern=r'^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
class RubricInput(Input):
    title:str=Field(min_length=1,max_length=180)
    markdown:str=Field(min_length=1,max_length=30000)
class Parameter(Input):
    questionType:Literal['single_choice','short_answer','open_answer']='short_answer'
    count:int=Field(default=3,ge=1,le=20)
class ReferenceSelection(Input):
    kind:Literal['draft','material']
    id:UUID
class RunInput(Input):
    referenceSources:list[ReferenceSelection]=Field(default_factory=list,max_length=8)
    taskType:Literal['lecture','practice','exam','project','manager']
    topic:str=Field(min_length=1,max_length=200)
    weekNumbers:list[int]=Field(default_factory=list,max_length=52)
    documentIds:list[UUID]=Field(default_factory=list,max_length=20)
    guidelines:str=Field(default='',max_length=10000)
    parameters:list[Parameter]=Field(default_factory=lambda:[Parameter()],max_length=3)
    courseStudentId:int|None=Field(default=None,ge=1)
    rubricVersionId:UUID|None=None
    parentRunId:UUID|None=None
    @model_validator(mode='after')
    def unique(self):
        if self.taskType=='exam' and (not self.parameters or sum(p.count for p in self.parameters)>40 or len({p.questionType for p in self.parameters})!=len(self.parameters)):raise ValueError('Choose unique question types, total 1-40')
        if self.referenceSources and self.taskType!='practice':raise ValueError('References are for practice')
        if len({(r.kind,r.id) for r in self.referenceSources})!=len(self.referenceSources):raise ValueError('Duplicate reference')
        for values in (self.weekNumbers,self.documentIds):
            if len(values)!=len(set(values)):raise ValueError('Duplicate selection')
        if any(w<1 or w>52 for w in self.weekNumbers):raise ValueError('Invalid week')
        return self
class ReviewInput(Input):
    expectedRevision:int=Field(ge=1)
    decision:Literal['approve','revise']
    feedback:str=Field(default='',max_length=10000)
class EditInput(Input):
    expectedRevision:int=Field(ge=1)
    draft:dict
class RetryInput(Input):
    expectedRevision:int=Field(ge=0)
class FeedbackInput(Input):
    rating:int=Field(ge=1,le=5)
    comment:str=Field(default='',max_length=2000)

from apps.api.educational_review import review_material,CRITERIA
class Judge:
 def __init__(self,score=2,quote='Defined concept',critical=None):self.score=score;self.quote=quote;self.critical=critical or []
 def invoke(self,messages):
  assert 'approvedOutline' in messages[1].content
  return {'criteria':[{'criterionId':k,'score':self.score,'evidenceQuotes':[self.quote] if self.quote else [],'rationale':'Synthetic evidence','nextAction':'Compare the worked example'} for k in CRITERIA],'criticalIssues':self.critical}
def review(judge):return review_material('Defined concept',{'main_slides':['Concept']},'Goal','Evidence',[],judge)
def test_status_and_provenance():
 r=review(Judge());assert r['status']=='readyForInstructorReview' and r['humanReviewRequired']
 assert len(r['outputHash'])==64 and r['validatedEducationalEffect'] is False
 assert review(Judge(score=1))['status']=='needsRevision'
 assert review(Judge(score=None))['status']=='inconclusive'
 assert review(Judge(critical=['Unsupported conclusion']))['status']=='needsRevision'
def test_fabricated_evidence_or_missing_criteria_never_pass():
 assert review(Judge(quote='Not in material'))['status']=='inconclusive'
 assert review(Judge(quote=''))['status']=='inconclusive'
 class Broken:
  def invoke(self,messages):return {'criteria':[],'criticalIssues':[]}
 assert review(Broken())['status']=='reviewFailed'
 class Failed:
  def invoke(self,messages):raise TimeoutError('secret must not leak')
 assert 'secret' not in str(review(Failed()))


def test_demo_never_invokes_judge(monkeypatch):
 from apps.api.legacy_runner import demo
 import apps.api.educational_review as module
 monkeypatch.setattr(module,'review_material',lambda *a: (_ for _ in ()).throw(AssertionError('No live model in demo')))
 r=demo({'request':{'task_type':'lecture','topic':'Synthetic','week':1,'parameters':[],'roster':[]},'phase':'finalize','draft':{'main_slides':['## Test']}})
 assert r['educationReview']['status']=='notEvaluated'

def test_paragraph_references_extract_original_text():
 class ParagraphJudge(Judge):
  def invoke(self,messages):
   r=super().invoke(messages)
   for c in r['criteria']:c.update(evidenceQuotes=[],evidenceParagraphIds=[1])
   return r
 r=review(ParagraphJudge())
 assert r['status']=='readyForInstructorReview'
 assert all(c['evidenceQuotes']==['Defined concept'] for c in r['criteria'])

"""
MENTAURI - Human Potential Navigation System
FastAPI Backend with Gemini integration
"""
import os, json, re, io, uuid, asyncio, sys
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

# -------- Auto-load .env if present (no python-dotenv dep needed) --------
def _load_dotenv():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
_load_dotenv()

from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, Boolean, Float, Text, Date, DateTime, ForeignKey, JSON as SAJSON
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
import httpx

# -------- DB Setup --------
DB_PATH = Path(__file__).parent / "data" / "mentauri.db"
DB_PATH.parent.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# -------- Models --------
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(120))
    email = Column(String(120))
    language = Column(String(5), default="en")
    college = Column(String(200))
    branch = Column(String(100))
    year_of_study = Column(Integer, default=1)
    cgpa = Column(Float)
    github_url = Column(String(300))
    linkedin_url = Column(String(300))
    target_role = Column(String(120))
    onboarding_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    gemini_api_key = Column(String(200))  # per-visitor BYOK key; NULL if not set

class PersonalityProfile(Base):
    __tablename__ = "personality_profiles"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), unique=True)
    openness = Column(Float, default=0.5)
    conscientiousness = Column(Float, default=0.5)
    extraversion = Column(Float, default=0.5)
    agreeableness = Column(Float, default=0.5)
    neuroticism = Column(Float, default=0.5)
    learning_style = Column(String(20), default="visual")
    work_style = Column(String(30), default="collaborative")
    risk_appetite = Column(Float, default=0.5)
    motivation_summary = Column(Text, default="")
    strengths = Column(Text, default="[]")  # JSON list
    weaknesses = Column(Text, default="[]")
    operating_manual = Column(Text, default="")
    native_habitat = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class AssessmentResponse(Base):
    __tablename__ = "assessment_responses"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    question_id = Column(Integer)
    value = Column(Integer)
    dimension = Column(String(40))
    created_at = Column(DateTime, default=datetime.utcnow)

class Skill(Base):
    __tablename__ = "skills"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String(100))
    level = Column(String(20), default="basic")  # none/basic/intermediate/advanced
    source = Column(String(30), default="manual")
    created_at = Column(DateTime, default=datetime.utcnow)

class Goal(Base):
    __tablename__ = "goals"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    title = Column(String(240))
    role_target = Column(String(120))
    timeline_months = Column(Integer, default=12)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)

class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    title = Column(String(200))
    description = Column(Text)
    tech_stack = Column(Text, default="[]")
    url = Column(String(400))
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(240))
    type = Column(String(40))
    organizer = Column(String(200))
    description = Column(Text)
    location = Column(String(120))
    stipend = Column(String(80))
    deadline = Column(String(40))
    url = Column(String(500))
    eligibility = Column(Text, default="")
    skills_required = Column(Text, default="[]")  # JSON
    skills_gained = Column(Text, default="[]")
    difficulty = Column(Integer, default=3)
    time_commitment = Column(String(40))
    verified = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class OpportunityInteraction(Base):
    __tablename__ = "opportunity_interactions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    opportunity_id = Column(String, ForeignKey("opportunities.id"))
    action = Column(String(20))  # view/save/apply/reject
    created_at = Column(DateTime, default=datetime.utcnow)

class Checkin(Base):
    __tablename__ = "checkins"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    date = Column(Date, default=date.today)
    energy = Column(Integer, default=3)
    productivity = Column(Integer, default=3)
    hours_slept = Column(Float, default=7)
    exercised = Column(Boolean, default=False)
    free_text = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class MomentumSnapshot(Base):
    __tablename__ = "momentum_snapshots"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    date = Column(Date, default=date.today)
    score = Column(Integer, default=0)
    components = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

class BurnoutSnapshot(Base):
    __tablename__ = "burnout_snapshots"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    date = Column(Date, default=date.today)
    risk_score = Column(Integer, default=0)
    band = Column(String(10), default="green")
    signals = Column(Text, default="{}")
    recommendation = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class SimulationPath(Base):
    __tablename__ = "simulation_paths"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    goal_id = Column(String, ForeignKey("goals.id"), nullable=True)
    goal_role = Column(String(120))
    paths_json = Column(Text)  # full result
    created_at = Column(DateTime, default=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    role = Column(String(20))  # user/assistant/system
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class Todo(Base):
    __tablename__ = "todos"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    title = Column(String(300))
    category = Column(String(40), default="general")  # general/skill/opportunity/project/ai-suggested
    priority = Column(String(10), default="medium")  # low/medium/high
    completed = Column(Boolean, default=False)
    due_date = Column(Date, nullable=True)
    linked_opportunity_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

Base.metadata.create_all(bind=engine)
# NOTE: create_all only creates missing TABLES, it does not add new
# COLUMNS to an existing table. If you're running locally with an old
# data/mentauri.db from before the gemini_api_key column was added,
# delete that file (or the whole data/ folder) once so it's recreated
# with the current schema. Render's free tier resets its filesystem on
# every redeploy, so this doesn't affect the hosted deployment.

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# -------- GEMINI CLIENT --------
from google import genai
from google.genai import types

class GeminiQuotaExceeded(Exception):
    """Raised when Gemini returns a 429 / RESOURCE_EXHAUSTED quota error."""
    pass

class GeminiTimeout(Exception):
    """Raised when a Gemini call takes too long and is aborted client-side."""
    pass

def _is_quota_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        "429" in msg
        or "resource_exhausted" in msg
        or "resource has been exhausted" in msg
        or "exceeded your current quota" in msg
        or "quota" in msg and "exceed" in msg
    )

def _is_timeout_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        "timeout" in msg
        or "timed out" in msg
        or "deadline_exceeded" in msg
        or "deadline exceeded" in msg
    )

# Ordered list of model names to try (newest / preferred first)
# Ordered list of model names to try (newest / preferred first).
#
# IMPORTANT — keep this list current, or every visitor's key will hit
# silent 404s once Google retires an old model. As of the last check
# (per https://ai.google.dev/gemini-api/docs/deprecations):
#   - gemini-3.7-flash   -> newest, no shutdown date announced
#   - gemini-3.6-flash   -> GA/stable since 21 Jul 2026, no shutdown date
#   - gemini-3.5-flash-lite -> GA, cheap/fast fallback
#   - gemini-2.5-flash   -> shuts down 16 Oct 2026 — remove after that date
#   - gemini-2.0-flash / gemini-1.5-flash -> ALREADY shut down, do not use
#   - gemini-flash-latest -> deliberately NOT used here: this alias can
#     silently swap to an experimental/preview model with tighter rate
#     limits, which caused real production 404s for other teams. Pin
#     explicit versions instead, and update this one list when Google
#     announces a new deprecation.
GEMINI_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",  # TODO: remove after 16 Oct 2026 shutdown
]

def get_gemini_client(api_key: str):
    # The SDK defaults to no client-side timeout (waits on the server
    # forever), which is a known cause of requests hanging indefinitely
    # under load. 25s keeps us well under the frontend's own 30s abort.
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=25_000))

def _generate_with_fallback(client, contents, config=None):
    """Try GEMINI_MODELS in order; return first successful response."""
    last_err = None
    for model in GEMINI_MODELS:
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
            return resp
        except Exception as e:
            last_err = e
            if _is_quota_error(e) or _is_timeout_error(e):
                # Quota exhaustion or a stalled request on this model won't
                # be fixed by retrying the same model, but a later model in
                # the list occasionally sits on a separate quota bucket,
                # so we still try the rest before giving up.
                continue
            msg = str(e).lower()
            # Only fall through for "model not found" / deprecation errors, not other errors
            if "404" in msg or "not found" in msg or "no longer available" in msg or "deprecated" in msg:
                continue
            raise
    if last_err:
        if _is_quota_error(last_err):
            raise GeminiQuotaExceeded(str(last_err))
        if _is_timeout_error(last_err):
            raise GeminiTimeout(str(last_err))
    raise last_err if last_err else RuntimeError("No Gemini model worked")

def call_gemini(api_key: str, prompt: str, system: str = None, json_mode: bool = True, temperature: float = 0.7):
    """Call Gemini with structured JSON output. Returns parsed JSON or raises."""
    client = get_gemini_client(api_key)
    cfg = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )
    contents = []
    if system:
        contents.append(types.Content(parts=[types.Part.from_text(text="SYSTEM: "+system)], role="user"))
        contents.append(types.Content(parts=[types.Part.from_text(text="Understood.")], role="model"))
    contents.append(types.Content(parts=[types.Part.from_text(text=prompt)], role="user"))
    resp = _generate_with_fallback(client, contents, cfg)
    text = resp.text
    # Strip markdown code fences if any
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    if json_mode:
        try:
            return json.loads(text)
        except Exception:
            # Try to extract first {...} or [...] block
            m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            raise ValueError(f"Gemini did not return valid JSON: {text[:200]}")
    return text

# -------- Pydantic Schemas --------
class StartReq(BaseModel):
    name: str
    language: str = "en"
    college: Optional[str] = ""
    branch: Optional[str] = ""
    year: int = 1
    cgpa: Optional[float] = None

class AnswerReq(BaseModel):
    question_id: int
    value: int
    dimension: str

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    college: Optional[str] = None
    branch: Optional[str] = None
    year_of_study: Optional[int] = None
    cgpa: Optional[float] = None
    github_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    target_role: Optional[str] = None

class ChatReq(BaseModel):
    message: str

class GoalReq(BaseModel):
    role_target: str
    timeline_months: int = 12

class CheckinReq(BaseModel):
    energy: int
    productivity: int
    hours_slept: float
    exercised: bool
    free_text: str = ""

class SkillReq(BaseModel):
    name: str
    level: str = "basic"

class ProjectReq(BaseModel):
    title: str
    description: str = ""
    tech_stack: str = ""
    url: str = ""

class TodoReq(BaseModel):
    title: str
    category: str = "general"
    priority: str = "medium"
    due_date: Optional[str] = None  # ISO date YYYY-MM-DD
    linked_opportunity_id: Optional[str] = None

class TodoUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    completed: Optional[bool] = None
    due_date: Optional[str] = None

# -------- AUTH (simple header-based) --------
def get_user(x_user_id: str = Header(None, alias="x-user-id"), db: Session = Depends(get_db)):
    if not x_user_id:
        raise HTTPException(401, "No user id. Create a session first via POST /start")
    user = db.query(User).filter_by(id=x_user_id).first()
    if not user:
        raise HTTPException(401, "Invalid user id")
    return user

# -------- Seed Data: Opportunities --------
SEED_OPPORTUNITIES = [
    {"title":"Smart India Hackathon (SIH)","type":"hackathon","organizer":"MoE Innovation Cell","description":"National hackathon solving real-world problems from ministries and PSUs. ₹1L+ prize pool per problem statement.","location":"Across India","stipend":"₹1,00,000 prize","deadline":"March 31 (annual)","url":"https://sih.gov.in","eligibility":"All engineering students, teams of 6","skills_required":["Python","Problem Solving","Teamwork","Presentation","Git"],"skills_gained":["Rapid Prototyping","Client Communication","Product Thinking"],"difficulty":3,"time_commitment":"6-8 weeks"},
    {"title":"Google Summer of Code (GSoC)","type":"fellowship","organizer":"Google Open Source","description":"Contribute to open-source projects over the summer with a stipend from Google. Global recognition, strong resume signal.","location":"Remote (global)","stipend":"$1500-$3000 stipend","deadline":"April (annual)","url":"https://summerofcode.withgoogle.com","eligibility":"Students 18+, open to all years","skills_required":["Git","One programming language","Open Source"],"skills_gained":["Large-scale collaboration","Code review","Mentorship"],"difficulty":4,"time_commitment":"12 weeks full-time"},
    {"title":"MITACS Globalink Research Internship","type":"research","organizer":"MITACS Canada","description":"Paid 12-week research internship at a Canadian university. Covers flight, stipend, visa support.","location":"Canada","stipend":"$9000 CAD grant + flight","deadline":"September (annual)","url":"https://www.mitacs.ca/globallink-research-internship","eligibility":"2nd/3rd year, CGPA 8.5+","skills_required":["Research","Technical Writing","Academic Reading"],"skills_gained":["Research methodology","International exposure","Faculty references"],"difficulty":4,"time_commitment":"12 weeks"},
    {"title":"DAAD WISE","type":"research","organizer":"DAAD Germany","description":"2-3 month research internship at a German university with a monthly stipend of €861.","location":"Germany","stipend":"€861/month + travel","deadline":"November (annual)","url":"https://www.daad.de","eligibility":"3rd/4th year, CGPA 8.5+","skills_required":["Research","Technical writing"],"skills_gained":["International research experience","Technical German (optional)"],"difficulty":4,"time_commitment":"2-3 months"},
    {"title":"Microsoft Engage Mentorship Program","type":"internship","organizer":"Microsoft","description":"Mentorship-driven program for 2nd/3rd year students leading to internship opportunity. Build a project with Microsoft mentors.","location":"Hybrid (India)","stipend":"Internship offer → ₹50k/month","deadline":"May (annual)","url":"https://microsoft.com/engage","eligibility":"2nd/3rd year students","skills_required":["Python/JS/Java","Problem Solving"],"skills_gained":["Industry mentorship","Production coding","Pipeline to SWE intern"],"difficulty":3,"time_commitment":"4-6 weeks part-time"},
    {"title":"Amazon ML Summer School","type":"fellowship","organizer":"Amazon","description":"Free 4-week ML program covering core ML concepts with Amazon scientists. PPO pipeline to ML internships.","location":"Virtual (India)","stipend":"Free; shortlist priority","deadline":"August (annual)","url":"https://amazonmlsummerschools.com","eligibility":"Pre-final year students","skills_required":["Python","Basic Math","Statistics"],"skills_gained":["Applied ML","Industry use cases","Network access"],"difficulty":2,"time_commitment":"4 weeks, 10hr/week"},
    {"title":"Tata Innovation Fellowship (NIF)","type":"scholarship","organizer":"NIF","description":"Fellowship and micro-grant funding for innovative student projects in technology and social impact.","location":"India","stipend":"Up to ₹5L project grant","deadline":"Rolling","url":"https://nif.org.in","eligibility":"Student innovators, all years","skills_required":["Innovation","Prototyping","Problem Framing"],"skills_gained":["Project funding","Patent support","Mentorship"],"difficulty":3,"time_commitment":"6 months project"},
    {"title":"Hack2Secure BSides Delhi Hackathon","type":"hackathon","organizer":"BSides Delhi","description":"Cybersecurity-focused hackathon with industry judges and cybersecurity firm recruiting.","location":"New Delhi","stipend":"₹50,000 prizes + job offers","deadline":"October (annual)","url":"https://bsidesdelhi.in","eligibility":"All years, cybersecurity interest","skills_required":["Networking","Python","Linux","Web Security"],"skills_gained":["Security specialization","Industry contacts","CTF experience"],"difficulty":4,"time_commitment":"Weekend + prep"},
    {"title":"Devfolio Hackathons (Multiple)","type":"hackathon","organizer":"Devfolio","description":"20+ high-quality hackathons annually across India (ETHIndia, InOut, HackCBS, etc.). Cash prizes + internship/full-time offers from sponsors.","location":"Hybrid","stipend":"₹1L-₹10L+ prizes per event","deadline":"Rolling","url":"https://devfolio.co/hackathons","eligibility":"All college students","skills_required":["Web Dev","Git","One framework"],"skills_gained":["Ship under pressure","Network","Sponsor recruiting"],"difficulty":3,"time_commitment":"24-36 hours"},
    {"title":"Kaggle Competition (Featured)","type":"competition","organizer":"Kaggle/Google","description":"Data science competitions with cash prizes and Kaggle Master ranks - strong signal for ML/DS roles.","location":"Online","stipend":"$1k-$100k+ prizes","deadline":"Rolling","url":"https://kaggle.com/competitions","eligibility":"Open","skills_required":["Python","Pandas","Scikit-learn","Data Viz"],"skills_gained":["ML practical skill","Ranking credibility","Community"],"difficulty":4,"time_commitment":"Flexible"},
    {"title":"Inspire Scholarship (DST)","type":"scholarship","organizer":"DST, Govt of India","description":"₹80,000/year scholarship for top 1% science students pursuing UG/PG in natural/basic sciences.","location":"India","stipend":"₹80,000/year","deadline":"November (annual)","url":"https://online-inspire.gov.in","eligibility":"Top 1% 12th science / JEE/NEET top 10k","skills_required":["Academic excellence","Science aptitude"],"skills_gained":["Financial independence","Research community"],"difficulty":3,"time_commitment":"5 years duration"},
    {"title":"Flipkart Runway / GRiD","type":"internship","organizer":"Flipkart","description":"Flipkart's flagship hiring challenge for women engineers (Runway) and general talent (GRiD) - leads to SWE internships.","location":"Bangalore/Remote","stipend":"₹50k/month internship","deadline":"February (annual)","url":"https://flipkart.com/careers","eligibility":"Pre-final year","skills_required":["DSA","System Design basics","One OOP language"],"skills_gained":["Large-scale systems","Industry intern offer"],"difficulty":4,"time_commitment":"8-12 weeks"},
    {"title":"Research@IIT SURGE / Internships","type":"research","organizer":"Various IITs","description":"Summer undergraduate research program at IIT Kanpur, Bombay, etc. with faculty mentors and stipend.","location":"IIT campuses","stipend":"₹12,500-₹25,000/month","deadline":"March-April (annual)","url":"https://surge.iitk.ac.in","eligibility":"2nd/3rd year, CGPA 8+","skills_required":["Academic fundamentals","Research interest"],"skills_gained":["LORs for MS/PhD","Research exposure","Paper publications"],"difficulty":3,"time_commitment":"8-10 weeks"},
    {"title":"Codeforces / CodeChef Contests (Monthly Long Challenges)","type":"competition","organizer":"Codeforces/CodeChef","description":"Competitive programming contests. Top 500 ranks on Codeforces are a strong signal for trading/HFT/top-tier SWE roles.","location":"Online","stipend":"Certificates; prizes in select events","deadline":"Weekly/Monthly","url":"https://codeforces.com","eligibility":"Open","skills_required":["C++/Java","DSA","Math"],"skills_gained":["Problem solving","Speed coding","Interview readiness"],"difficulty":4,"time_commitment":"2-5 hours/week"},
    {"title":"LinkedIn Learning Certifications","type":"learning","organizer":"LinkedIn/Microsoft","description":"Free LinkedIn Premium for students gives access to certifications; strong for LinkedIn profile strength.","location":"Online","stipend":"Free via GitHub Student Pack","deadline":"Anytime","url":"https://education.github.com/pack","eligibility":"College students","skills_required":["Self-discipline"],"skills_gained":["Industry-recognized certificates","Structured paths"],"difficulty":2,"time_commitment":"Self-paced"},
    {"title":"GitHub Student Developer Pack","type":"scholarship","organizer":"GitHub","description":"Free access to $200k+ worth of developer tools - JetBrains, AWS credits, Azure, Stripe, Canva, domains, etc.","location":"Online","stipend":"$200k+ in free tools","deadline":"Anytime","url":"https://education.github.com/pack","eligibility":"Verified students","skills_required":[],"skills_gained":["Professional toolchain","Project hosting","Credits"],"difficulty":1,"time_commitment":"1-time application"},
    {"title":"Charpak Lab Scholarship (France)","type":"research","organizer":"Campus France/IFCE","description":"1-3 month research internship in France with monthly stipend of ~€700 and visa support.","location":"France","stipend":"€700/month","deadline":"January (annual)","url":"https://inde.campusfrance.org/charpak-lab-scholarship","eligibility":"2nd/3rd year science/tech, CGPA 8+","skills_required":["Research","One European language preferred"],"skills_gained":["International research","French academic network"],"difficulty":4,"time_commitment":"1-3 months"},
    {"title":"Student Partner Programs (Microsoft Learn Ambassador / Google DSC / GitHub Campus Expert)","type":"leadership","organizer":"Microsoft/Google/GitHub","description":"Official student community programs with training, swag, events, and direct recruiter access.","location":"Your campus","stipend":"Swag, training, certifications","deadline":"Rolling","url":"https://studentambassadors.microsoft.com","eligibility":"Enrolled students, leadership potential","skills_required":["Communication","Community building","Tech fundamentals"],"skills_gained":["Leadership proof","Direct recruiter pipelines","Public speaking"],"difficulty":2,"time_commitment":"1 academic year"},
    {"title":"BIRAC-SRISTI Innovation Awards","type":"competition","organizer":"BIRAC","description":"Biotech/med-tech innovation awards for student projects addressing Indian health problems. Grants up to ₹50L.","location":"India","stipend":"Up to ₹50L grant","deadline":"Biannual","url":"https://birac.nic.in","eligibility":"Student innovators, biotech focus","skills_required":["Biology basics","Innovation","Prototyping"],"skills_gained":["Grant funding","Industry mentorship","Patent opportunities"],"difficulty":4,"time_commitment":"6+ months"},
    {"title":"ACM ICPC (International Collegiate Programming Contest)","type":"competition","organizer":"ACM","description":"Olympiad of programming. World Finals is the most prestigious CP competition. Regional medalists get major recruiting boosts.","location":"Regional/Worldwide","stipend":"Prizes + offers from FAANG/prop-trading firms","deadline":"November regionals","url":"https://icpc.global","eligibility":"First/second year students (age limit)","skills_required":["C++","Advanced DSA","Teamwork"],"skills_gained":["Elite problem-solving","Top-tier interview ready","Team competition"],"difficulty":5,"time_commitment":"3-6 months preparation"},
    {"title":"UPSC Civil Services Examination (CSE)","type":"exam","organizer":"UPSC, Govt of India","description":"India's premier civil services exam for IAS/IPS/IFS and allied services. Three stages: Prelims, Mains, Interview.","location":"Across India","stipend":"Government salary post-selection (Pay Level 10+)","deadline":"February notification (annual)","url":"https://upsc.gov.in","eligibility":"Graduates, age 21-32 (relaxations apply)","skills_required":["Current Affairs","Essay Writing","Analytical Reasoning","One optional subject mastery"],"skills_gained":["Public policy understanding","Administrative aptitude","Long-horizon discipline"],"difficulty":5,"time_commitment":"12-24 months preparation"},
    {"title":"State Public Service Commission Exams (State PCS)","type":"exam","organizer":"State PSCs (e.g. UPPSC, BPSC, MPPSC)","description":"State-level administrative service exams leading to roles like SDM, DSP, and other state civil services.","location":"State-specific","stipend":"Government salary post-selection","deadline":"Varies by state (annual)","url":"https://upsc.gov.in","eligibility":"Graduates, state domicile often required","skills_required":["State-specific GK","Current Affairs","Essay Writing"],"skills_gained":["Regional governance knowledge","Administrative exposure"],"difficulty":4,"time_commitment":"12-18 months preparation"},
    {"title":"CAT (Common Admission Test) for IIM/MBA","type":"exam","organizer":"IIMs","description":"India's premier MBA entrance exam. High percentile opens doors to IIMs and other top B-schools for a management career.","location":"Across India (computer-based)","stipend":"N/A (leads to placements post-MBA, often ₹15-30L+ CTC)","deadline":"August registration, November exam (annual)","url":"https://iimcat.ac.in","eligibility":"Graduates (final year eligible to apply)","skills_required":["Quantitative Aptitude","Verbal Ability","Data Interpretation","Logical Reasoning"],"skills_gained":["Case-based thinking","Time-pressured decision-making"],"difficulty":5,"time_commitment":"6-12 months preparation"},
    {"title":"Big 4 / Consulting Internship (Summer Analyst)","type":"internship","organizer":"McKinsey/BCG/Bain/Deloitte/EY","description":"Summer internship programs for pre-final year students, often converting into full-time consulting offers.","location":"Metro cities (India)","stipend":"₹1-2L/month stipend","deadline":"Campus-specific, typically August-September","url":"https://www.mckinsey.com/careers","eligibility":"Pre-final year, strong academics, case-interview readiness","skills_required":["Case Interview Prep","Structured Problem-Solving","Excel/PowerPoint","Communication"],"skills_gained":["Client-facing consulting skills","Business frameworks","Executive presence"],"difficulty":5,"time_commitment":"8-10 weeks"},
    {"title":"NEET-PG / INI-CET for Medical Postgraduation","type":"exam","organizer":"NBE / AIIMS","description":"Entrance exams for MD/MS postgraduate medical seats at government and INI (AIIMS/PGI/JIPMER) institutions.","location":"Across India","stipend":"N/A (leads to PG stipend post-selection, ₹60k-1L/month)","deadline":"Varies (annual)","url":"https://nbe.edu.in","eligibility":"MBBS graduates with completed internship","skills_required":["Subject mastery across MBBS curriculum","Time-bound MCQ practice"],"skills_gained":["Specialization pathway","Clinical depth"],"difficulty":5,"time_commitment":"12-18 months preparation"},
    {"title":"CLAT (Common Law Admission Test)","type":"exam","organizer":"Consortium of NLUs","description":"National entrance exam for undergraduate and postgraduate law programs at India's National Law Universities.","location":"Across India","stipend":"N/A (leads to law career, litigation or corporate)","deadline":"December exam (annual)","url":"https://consortiumofnlus.ac.in","eligibility":"12th pass (UG) or LLB graduates (PG)","skills_required":["Legal Reasoning","English Comprehension","Current Affairs","Logical Reasoning"],"skills_gained":["Legal aptitude","Structured argumentation"],"difficulty":4,"time_commitment":"6-12 months preparation"},
    {"title":"National Means-cum-Merit Scholarship / Central Sector Scheme","type":"scholarship","organizer":"Ministry of Education, Govt of India","description":"Merit-cum-means scholarships for undergraduate students across all disciplines, not limited to STEM.","location":"India","stipend":"₹10,000-₹20,000/year","deadline":"October (annual)","url":"https://scholarships.gov.in","eligibility":"Family income below threshold, merit-based","skills_required":["Academic merit"],"skills_gained":["Financial support","Access to further scholarships"],"difficulty":2,"time_commitment":"Application only"},
    {"title":"Teach For India Fellowship","type":"fellowship","organizer":"Teach For India","description":"2-year full-time fellowship teaching in low-income schools, building leadership and education-sector experience for any graduate.","location":"Across India (metro/semi-urban)","stipend":"₹18,000-₹22,000/month","deadline":"Rolling (multiple cohorts/year)","url":"https://teachforindia.org","eligibility":"Any graduate, any discipline","skills_required":["Communication","Empathy","Adaptability"],"skills_gained":["Leadership under constraints","Public/social sector network","Classroom management"],"difficulty":3,"time_commitment":"2 years full-time"},
    {"title":"Model United Nations (MUN) Circuit","type":"competition","organizer":"Various universities (Harvard MUN India, JNU MUN, etc.)","description":"Diplomacy and public-speaking competitions simulating UN committees — strong for law, policy, and international relations aspirants.","location":"Across India","stipend":"Awards/certificates; some cash prizes","deadline":"Rolling through the academic year","url":"https://harvardmunindia.org","eligibility":"Any college student","skills_required":["Public Speaking","Negotiation","Research","Current Affairs"],"skills_gained":["Diplomacy","Policy argumentation","Networking with policy circles"],"difficulty":3,"time_commitment":"Weekend events + prep"},
    {"title":"Chartered Accountancy (CA) via ICAI","type":"exam","organizer":"ICAI","description":"India's premier accounting/finance qualification — Foundation, Intermediate, and Final levels plus articleship.","location":"Across India","stipend":"Articleship stipend ₹8,000-15,000/month","deadline":"Rolling entry, exams in May/Nov","url":"https://icai.org","eligibility":"12th pass (Foundation) or graduates (direct entry)","skills_required":["Accounting fundamentals","Quantitative aptitude","Discipline"],"skills_gained":["Financial expertise","Audit and taxation skills","Professional credential"],"difficulty":5,"time_commitment":"3-5 years"},
]

def seed_opportunities(db: Session):
    if db.query(Opportunity).count() == 0:
        for o in SEED_OPPORTUNITIES:
            db.add(Opportunity(
                title=o["title"], type=o["type"], organizer=o["organizer"], description=o["description"],
                location=o["location"], stipend=o["stipend"], deadline=o["deadline"], url=o["url"],
                eligibility=o["eligibility"],
                skills_required=json.dumps(o["skills_required"]),
                skills_gained=json.dumps(o["skills_gained"]),
                difficulty=o["difficulty"], time_commitment=o["time_commitment"],
                verified=True
            ))
        db.commit()

with SessionLocal() as s:
    seed_opportunities(s)

# -------- Helpers --------
def compute_personality(responses: list):
    """Big-5 scoring from 1-5 responses. 30 questions mapped across 5 dimensions."""
    # Dimensions default to midpoint; compute weighted averages
    dims = {"openness":0.5,"conscientiousness":0.5,"extraversion":0.5,"agreeableness":0.5,"neuroticism":0.5}
    counts = {d:[] for d in dims}
    for r in responses:
        d = r.dimension
        if d in counts:
            v = r.value
            # approximate reverse-scoring: questions with id even are reverse for certain dims
            if r.question_id in [3, 8, 13, 18, 23, 28]:
                v = 6 - v
            counts[d].append(v)
    for d, vals in counts.items():
        if vals:
            dims[d] = (sum(vals)/len(vals) - 1) / 4  # normalize 1-5 → 0-1
    return dims

def compute_streak(user_id: str, db: Session) -> int:
    """Count consecutive days with a check-in up to today. Missing today = still keep yesterday's streak."""
    from datetime import timedelta
    checkins = db.query(Checkin).filter_by(user_id=user_id).order_by(Checkin.date.desc()).all()
    if not checkins:
        return 0
    dates = sorted({c.date for c in checkins}, reverse=True)
    today = date.today()
    # If no check-in today, streak starts counting from yesterday
    start = dates[0]
    if start > today:
        return 0
    if (today - start).days > 1:
        return 0
    streak = 1
    for i in range(1, len(dates)):
        if (dates[i-1] - dates[i]).days == 1:
            streak += 1
        else:
            break
    return streak

def longest_streak(user_id: str, db: Session) -> int:
    from datetime import timedelta
    checkins = db.query(Checkin).filter_by(user_id=user_id).order_by(Checkin.date.asc()).all()
    if not checkins:
        return 0
    dates = sorted({c.date for c in checkins})
    best = cur = 1
    for i in range(1, len(dates)):
        if (dates[i] - dates[i-1]).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best

def compute_momentum(user_id: str, db: Session) -> dict:
    skills_count = db.query(Skill).filter_by(user_id=user_id).count()
    projects_count = db.query(Project).filter_by(user_id=user_id, completed=True).count()
    goals_count = db.query(Goal).filter_by(user_id=user_id, status="active").count()
    interactions = db.query(OpportunityInteraction).filter_by(user_id=user_id).count()
    todos_done = db.query(Todo).filter_by(user_id=user_id, completed=True).count()
    todos_total = db.query(Todo).filter_by(user_id=user_id).count()
    streak = compute_streak(user_id, db)
    checkins = db.query(Checkin).filter_by(user_id=user_id).order_by(Checkin.date.desc()).limit(30).all()
    consistency = min(len(checkins)/7, 1) if checkins else 0
    # components 0-100
    components = {
        "skills": min(skills_count*10, 100),
        "projects": min(projects_count*20, 100),
        "goals": min(goals_count*15, 100),
        "opportunities": min(interactions*8, 100),
        "todos": min(todos_done*8, 100),
        "streak": min(streak*10, 100),
        "consistency": int(consistency*100),
    }
    weights = {"skills":0.15,"projects":0.15,"goals":0.10,"opportunities":0.10,"todos":0.10,"streak":0.15,"consistency":0.25}
    score = int(sum(components[k]*weights[k] for k in weights))
    return {"score": score, "components": components, "streak": streak, "todos_done": todos_done, "todos_total": todos_total}

def compute_burnout(user_id: str, db: Session) -> dict:
    checkins = db.query(Checkin).filter_by(user_id=user_id).order_by(Checkin.date.desc()).limit(7).all()
    if not checkins:
        return {"risk_score":15, "band":"green", "signals":{}, "recommendation":"Not enough data yet — start logging daily check-ins so I can watch for burnout patterns for you."}
    avg_energy = sum(c.energy for c in checkins)/len(checkins)
    avg_prod = sum(c.productivity for c in checkins)/len(checkins)
    avg_sleep = sum(c.hours_slept for c in checkins)/len(checkins)
    exercise_ratio = sum(1 for c in checkins if c.exercised)/len(checkins)
    trend_energy = checkins[0].energy - (sum(c.energy for c in checkins[-3:])/min(3,len(checkins))) if len(checkins)>=3 else 0
    signals = {
        "low_energy": avg_energy < 2.5,
        "declining_energy": trend_energy < -0.5,
        "poor_sleep": avg_sleep < 6.5,
        "no_exercise": exercise_ratio < 0.2,
        "low_productivity": avg_prod < 2.5,
    }
    risk = 15
    if signals["low_energy"]: risk += 25
    if signals["declining_energy"]: risk += 20
    if signals["poor_sleep"]: risk += 20
    if signals["no_exercise"]: risk += 10
    if signals["low_productivity"]: risk += 15
    risk = min(risk, 100)
    if risk < 35: band = "green"
    elif risk < 65: band = "yellow"
    else: band = "red"
    rec_map = {
        "green":"You're in a sustainable rhythm. Keep protecting sleep and one non-negotiable deep-work block per day.",
        "yellow":"You're showing early signs of fatigue. Drop one non-critical commitment this week, protect one evening fully off, and prioritize 7+ hours of sleep tonight.",
        "red":"You're at risk of burnout. This is not failure — it's a signal. Take 48 hours at reduced load, talk to a friend/family member, and consider reaching out to a counselor at iCall (9152987821) or Vandrevala Foundation (1860-2662-345)."
    }
    return {"risk_score":risk, "band":band, "signals":signals, "recommendation":rec_map[band]}

def build_user_context(user: User, db: Session) -> str:
    """Build a context string about the user to inject into Gemini prompts."""
    profile = db.query(PersonalityProfile).filter_by(user_id=user.id).first()
    skills = [s.name for s in db.query(Skill).filter_by(user_id=user.id).all()]
    projects = [{"title":p.title,"desc":p.description,"tech":p.tech_stack,"done":p.completed} for p in db.query(Project).filter_by(user_id=user.id).all()]
    goals = [{"role":g.role_target,"timeline":g.timeline_months,"status":g.status} for g in db.query(Goal).filter_by(user_id=user.id).all()]
    checkins = db.query(Checkin).filter_by(user_id=user.id).order_by(Checkin.date.desc()).limit(7).all()
    momentum = compute_momentum(user.id, db)
    burnout = compute_burnout(user.id, db)
    ctx = {
        "name": user.name,
        "college": user.college,
        "branch": user.branch,
        "year": user.year_of_study,
        "cgpa": user.cgpa,
        "github": user.github_url,
        "linkedin": user.linkedin_url,
        "target_role": user.target_role,
        "onboarded": user.onboarding_completed,
        "personality": {
            "openness": profile.openness if profile else None,
            "conscientiousness": profile.conscientiousness if profile else None,
            "extraversion": profile.extraversion if profile else None,
            "agreeableness": profile.agreeableness if profile else None,
            "neuroticism": profile.neuroticism if profile else None,
            "learning_style": profile.learning_style if profile else None,
            "work_style": profile.work_style if profile else None,
            "risk_appetite": profile.risk_appetite if profile else None,
            "strengths": json.loads(profile.strengths) if profile and profile.strengths else [],
            "weaknesses": json.loads(profile.weaknesses) if profile and profile.weaknesses else [],
        },
        "skills": skills,
        "projects": projects,
        "goals": goals,
        "recent_energy_avg": round(sum(c.energy for c in checkins)/len(checkins),1) if checkins else None,
        "momentum_score": momentum["score"],
        "burnout_band": burnout["band"],
    }
    return json.dumps(ctx, indent=2, default=str)

# ========== ASSESSMENT QUESTIONS ==========
ASSESSMENT_QUESTIONS = [
    # Openness (1-6)
    {"id":1,"dimension":"openness","prompt":"I enjoy trying new things and experimenting with novel ideas.","reverse":False},
    {"id":2,"dimension":"openness","prompt":"I am curious about how things work and why.","reverse":False},
    {"id":3,"dimension":"openness","prompt":"I prefer familiar routines over new experiences.","reverse":True},
    {"id":4,"dimension":"openness","prompt":"I often imagine myself in different futures and careers.","reverse":False},
    {"id":5,"dimension":"openness","prompt":"I enjoy art, music, or creative expression.","reverse":False},
    {"id":6,"dimension":"openness","prompt":"I feel excited when learning about a completely new topic.","reverse":False},
    # Conscientiousness (7-12)
    {"id":7,"dimension":"conscientiousness","prompt":"I plan my day/week in advance rather than winging it.","reverse":False},
    {"id":8,"dimension":"conscientiousness","prompt":"I often leave assignments to the last minute.","reverse":True},
    {"id":9,"dimension":"conscientiousness","prompt":"I pay attention to details in my work.","reverse":False},
    {"id":10,"dimension":"conscientiousness","prompt":"When I start a project, I finish it even when it's hard.","reverse":False},
    {"id":11,"dimension":"conscientiousness","prompt":"I keep my workspace and files organized.","reverse":False},
    {"id":12,"dimension":"conscientiousness","prompt":"I set clear goals and track progress toward them.","reverse":False},
    # Extraversion (13-18)
    {"id":13,"dimension":"extraversion","prompt":"I feel energized after spending time with a group of people.","reverse":False},
    {"id":14,"dimension":"extraversion","prompt":"I enjoy meeting new people and striking up conversations.","reverse":False},
    {"id":15,"dimension":"extraversion","prompt":"I prefer working alone rather than in teams.","reverse":True},
    {"id":16,"dimension":"extraversion","prompt":"I tend to speak up in group discussions or classes.","reverse":False},
    {"id":17,"dimension":"extraversion","prompt":"I enjoy being the center of attention at times.","reverse":False},
    {"id":18,"dimension":"extraversion","prompt":"Large social events drain me and I need alone time to recover.","reverse":True},
    # Agreeableness (19-24)
    {"id":19,"dimension":"agreeableness","prompt":"I care about how other people feel and try to be empathetic.","reverse":False},
    {"id":20,"dimension":"agreeableness","prompt":"I enjoy helping others even when it inconveniences me.","reverse":False},
    {"id":21,"dimension":"agreeableness","prompt":"Competition matters more to me than collaboration.","reverse":True},
    {"id":22,"dimension":"agreeableness","prompt":"I tend to avoid conflict and keep the peace.","reverse":False},
    {"id":23,"dimension":"agreeableness","prompt":"I trust people easily and assume good intentions.","reverse":False},
    {"id":24,"dimension":"agreeableness","prompt":"I would describe myself as cooperative and team-oriented.","reverse":False},
    # Neuroticism (25-30)
    {"id":25,"dimension":"neuroticism","prompt":"I often feel anxious or worried about my future.","reverse":False},
    {"id":26,"dimension":"neuroticism","prompt":"My mood changes frequently and I can be emotionally volatile.","reverse":False},
    {"id":27,"dimension":"neuroticism","prompt":"I handle stress well and stay calm under pressure.","reverse":True},
    {"id":28,"dimension":"neuroticism","prompt":"I feel overwhelmed easily when I have multiple deadlines.","reverse":False},
    {"id":29,"dimension":"neuroticism","prompt":"I am generally relaxed and optimistic.","reverse":True},
    {"id":30,"dimension":"neuroticism","prompt":"I take setbacks personally and ruminate on them for days.","reverse":False},
    # Learning & Risk (31-35)
    {"id":31,"dimension":"learning_style","prompt":"I understand best when I see diagrams, charts, and visual demonstrations.","reverse":False},
    {"id":32,"dimension":"learning_style","prompt":"I enjoy listening to lectures, podcasts, and explanations more than reading.","reverse":False},
    {"id":33,"dimension":"learning_style","prompt":"I learn most by doing — hands-on projects, labs, or coding.","reverse":False},
    {"id":34,"dimension":"risk_appetite","prompt":"I would quit a stable path to build or join a risky early-stage startup.","reverse":False},
    {"id":35,"dimension":"risk_appetite","prompt":"I prefer a stable, well-paying job over uncertain but high-upside opportunities.","reverse":True},
]

def determine_learning_style(responses_map: dict) -> str:
    # Use Q31 (visual), Q32 (auditory), Q33 (kinesthetic) plus a read/write default
    v = responses_map.get(31,3); a = responses_map.get(32,3); k = responses_map.get(33,3)
    scores = {"visual":v, "auditory":a, "kinesthetic":k, "reading":3}
    return max(scores, key=scores.get)

def determine_work_style(responses_map: dict, dims: dict) -> str:
    if dims["extraversion"] > 0.65 and dims["conscientiousness"] < 0.5: return "collaborative"
    if dims["extraversion"] < 0.35 and dims["conscientiousness"] > 0.6: return "deep-worker"
    if dims["openness"] > 0.65: return "creative-explorer"
    return "structured-collaborative"

print("Backend module loaded successfully")

# ============ APP & ROUTES ============
app = FastAPI(title="MENTAURI API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(GeminiQuotaExceeded)
async def gemini_quota_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "The AI is getting a lot of requests right now and has hit its free quota. "
                      "This usually resets soon (daily limits reset at midnight Pacific Time, and "
                      "per-minute limits clear within a minute). The rest of MENTAURI — dashboard, "
                      "opportunity atlas, tasks, streaks — still works normally in the meantime.",
            "error_type": "quota_exceeded",
        },
    )

@app.exception_handler(GeminiTimeout)
async def gemini_timeout_handler(request, exc):
    return JSONResponse(
        status_code=504,
        content={
            "detail": "The AI took too long to respond and the request was stopped. "
                      "This can happen when the AI is under heavy load — try again in a moment.",
            "error_type": "timeout",
        },
    )

# Serve static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ---- Gemini key: per-visitor (BYOK) ----
# Each visitor pastes their own free key, stored on their own User row.
# GEMINI_API_KEY in the environment is intentionally NOT used to silently
# satisfy every visitor — that was the old shared-key design, and it meant
# one person's usage (or Google's daily quota) could lock out everyone
# else. It's still honored as a solo/local-dev convenience: if you're
# running this yourself with your own .env key, MENTAURI DEV MODE below
# can pre-fill it for your own testing, but it's off by default for
# anyone deployed publicly.
DEV_MODE_ENV_KEY = os.environ.get("MENTAURI_DEV_PREFILL_KEY", "").strip()  # opt-in only

@app.get("/")
def index():
    return FileResponse(str(static_dir / "index.html"))

@app.post("/api/settings")
def save_gemini_key(payload: dict = Body(...), user: User = Depends(get_user), db: Session = Depends(get_db)):
    api_key = payload.get("gemini_api_key","").strip()
    if not api_key:
        raise HTTPException(400, "API key required")
    # Validate by making a tiny call
    try:
        client = get_gemini_client(api_key)
        _generate_with_fallback(client, "ping")
    except Exception as e:
        raise HTTPException(400, f"Invalid Gemini API key: {e}")
    user.gemini_api_key = api_key
    db.commit()
    return {"ok":True}

@app.get("/api/settings")
def get_settings(user: User = Depends(get_user)):
    has = bool(user.gemini_api_key) or bool(DEV_MODE_ENV_KEY)
    return {"has_key": has, "from_env": bool(DEV_MODE_ENV_KEY and not user.gemini_api_key)}

def require_key(user: User):
    k = user.gemini_api_key or DEV_MODE_ENV_KEY
    if not k:
        raise HTTPException(428, "Gemini API key not configured. Add your own free key via the UI.")
    return k

# ---- Session start ----
@app.post("/api/start")
def start(req: StartReq, db: Session = Depends(get_db)):
    user = User(name=req.name, language=req.language, college=req.college, branch=req.branch,
                year_of_study=req.year, cgpa=req.cgpa)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "name": user.name}

# ---- Me ----
@app.get("/api/me")
def me(user: User = Depends(get_user), db: Session = Depends(get_db)):
    p = db.query(PersonalityProfile).filter_by(user_id=user.id).first()
    momentum = compute_momentum(user.id, db)
    burnout = compute_burnout(user.id, db)
    streak = compute_streak(user.id, db)
    todos_pending = db.query(Todo).filter_by(user_id=user.id, completed=False).count()
    todos_done = db.query(Todo).filter_by(user_id=user.id, completed=True).count()
    return {
        "id": user.id,
        "name": user.name,
        "college": user.college,
        "branch": user.branch,
        "year": user.year_of_study,
        "cgpa": user.cgpa,
        "github_url": user.github_url,
        "linkedin_url": user.linkedin_url,
        "target_role": user.target_role,
        "onboarding_completed": user.onboarding_completed,
        "personality": {
            "openness": p.openness if p else 0.5,
            "conscientiousness": p.conscientiousness if p else 0.5,
            "extraversion": p.extraversion if p else 0.5,
            "agreeableness": p.agreeableness if p else 0.5,
            "neuroticism": p.neuroticism if p else 0.5,
            "learning_style": p.learning_style if p else "visual",
            "work_style": p.work_style if p else "structured-collaborative",
            "risk_appetite": p.risk_appetite if p else 0.5,
            "strengths": json.loads(p.strengths) if p and p.strengths else [],
            "weaknesses": json.loads(p.weaknesses) if p and p.weaknesses else [],
            "operating_manual": p.operating_manual if p else "",
            "native_habitat": p.native_habitat if p else "",
        } if p else None,
        "momentum": momentum,
        "burnout": burnout,
        "streak": streak,
        "todos_pending": todos_pending,
        "todos_done": todos_done,
    }

@app.patch("/api/me")
def update_me(update: ProfileUpdate, user: User = Depends(get_user), db: Session = Depends(get_db)):
    for k, v in update.dict(exclude_unset=True).items():
        setattr(user, k, v)
    db.commit()
    return {"ok": True}

# ---- Assessment ----
@app.get("/api/assessment/questions")
def get_questions():
    return ASSESSMENT_QUESTIONS

@app.post("/api/assessment/answer")
def submit_answer(req: AnswerReq, user: User = Depends(get_user), db: Session = Depends(get_db)):
    r = AssessmentResponse(user_id=user.id, question_id=req.question_id, value=req.value, dimension=req.dimension)
    db.add(r)
    db.commit()
    return {"ok": True, "answered": db.query(AssessmentResponse).filter_by(user_id=user.id).count()}

@app.post("/api/assessment/finish")
def finish_assessment(user: User = Depends(get_user), db: Session = Depends(get_db)):
    key = require_key(user)
    responses = db.query(AssessmentResponse).filter_by(user_id=user.id).all()
    if len(responses) < 20:
        raise HTTPException(400, f"Please answer at least 20 questions (you have {len(responses)}).")
    dims = compute_personality(responses)
    resp_map = {r.question_id: r.value for r in responses}
    learning_style = determine_learning_style(resp_map)
    work_style = determine_work_style(resp_map, dims)
    # risk appetite from Q34/Q35
    q34 = resp_map.get(34,3); q35 = resp_map.get(35,3); q35r = 6 - q35
    risk = ((q34-1)/4 + (q35r-1)/4)/2

    # Ask Gemini for a rich profile
    ctx = {
        "name": user.name, "college": user.college, "branch": user.branch,
        "year": user.year_of_study, "cgpa": user.cgpa,
        "big5": dims, "learning_style": learning_style, "work_style": work_style,
        "risk_appetite": round(risk,2)
    }
    prompt = f"""You are MENTAURI, a Human Potential Navigation AI. Given this student's Big-5 personality assessment + context, return a JSON object with:
{{
  "strengths": [array of 5 strings, each a concrete strength this person has based on their profile, phrased as an empowering superpower],
  "weaknesses": [array of 3 potential blind-spots / growth areas phrased kindly and constructively],
  "operating_manual": string (3-4 sentences written in second person: "You do your best work when... You thrive in environments that... You should watch out for... Ideal teammates/mentors for you are..."),
  "native_habitat": string (2-3 sentences describing the kind of roles, team cultures, and work environments this person will naturally flourish in — e.g. "deep-work-first R&D teams", "fast-moving startup crews", "collaborative research labs", etc.),
  "motivation_summary": string (2 sentences on what likely drives this person and what kinds of problems they would find most meaningful)
}}

Student data: {json.dumps(ctx, indent=2)}

Return ONLY the JSON object, no prose. Be specific and insightful — not generic."""
    try:
        result = call_gemini(key, prompt, temperature=0.7)
    except Exception as e:
        # Graceful fallback
        result = {
            "strengths": ["Creative problem-solving","Self-awareness","Adaptability","Clear communication","Persistence"],
            "weaknesses": ["Can spread focus too thin","Needs active feedback loops","Prone to overthinking under stress"],
            "operating_manual": f"{user.name}, you do your best work when you have a clear 'why' behind the task, space to think deeply, and small wins along the way. You thrive when you can balance structure with creative exploration.",
            "native_habitat": "Environments that give you autonomy to shape your work while providing mentorship and growth opportunities.",
            "motivation_summary": "You are driven by meaningful impact and continuous growth. Problems that let you learn while contributing to something larger than yourself will energize you most."
        }

    profile = db.query(PersonalityProfile).filter_by(user_id=user.id).first()
    if not profile:
        profile = PersonalityProfile(user_id=user.id)
        db.add(profile)
    profile.openness = dims["openness"]
    profile.conscientiousness = dims["conscientiousness"]
    profile.extraversion = dims["extraversion"]
    profile.agreeableness = dims["agreeableness"]
    profile.neuroticism = dims["neuroticism"]
    profile.learning_style = learning_style
    profile.work_style = work_style
    profile.risk_appetite = risk
    profile.strengths = json.dumps(result["strengths"])
    profile.weaknesses = json.dumps(result["weaknesses"])
    profile.operating_manual = result["operating_manual"]
    profile.native_habitat = result["native_habitat"]
    profile.motivation_summary = result["motivation_summary"]
    user.onboarding_completed = True
    db.commit()
    return {"ok":True, "profile": {**dims, "learning_style":learning_style, "work_style":work_style, "risk_appetite":risk, **result}}

# ---- Skills ----
@app.get("/api/skills")
def list_skills(user: User = Depends(get_user), db: Session = Depends(get_db)):
    skills = db.query(Skill).filter_by(user_id=user.id).all()
    return [{"id":s.id,"name":s.name,"level":s.level,"source":s.source} for s in skills]

@app.post("/api/skills")
def add_skill(req: SkillReq, user: User = Depends(get_user), db: Session = Depends(get_db)):
    s = Skill(user_id=user.id, name=req.name, level=req.level)
    db.add(s); db.commit(); db.refresh(s)
    return {"ok":True,"id":s.id}

@app.delete("/api/skills/{sid}")
def del_skill(sid: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    s = db.query(Skill).filter_by(id=sid, user_id=user.id).first()
    if s: db.delete(s); db.commit()
    return {"ok":True}

# ---- Projects ----
@app.get("/api/projects")
def list_projects(user: User = Depends(get_user), db: Session = Depends(get_db)):
    ps = db.query(Project).filter_by(user_id=user.id).all()
    return [{"id":p.id,"title":p.title,"description":p.description,"tech_stack":json.loads(p.tech_stack or '[]'),"url":p.url,"completed":p.completed} for p in ps]

@app.post("/api/projects")
def add_project(req: ProjectReq, user: User = Depends(get_user), db: Session = Depends(get_db)):
    tech = [t.strip() for t in req.tech_stack.split(",") if t.strip()] if req.tech_stack else []
    p = Project(user_id=user.id, title=req.title, description=req.description, tech_stack=json.dumps(tech), url=req.url)
    db.add(p); db.commit(); db.refresh(p)
    return {"ok":True,"id":p.id}

@app.post("/api/projects/{pid}/complete")
def complete_project(pid: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    p = db.query(Project).filter_by(id=pid, user_id=user.id).first()
    if p: p.completed = True; db.commit()
    return {"ok":True}

@app.delete("/api/projects/{pid}")
def del_project(pid: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    p = db.query(Project).filter_by(id=pid, user_id=user.id).first()
    if p: db.delete(p); db.commit()
    return {"ok":True}

# ---- Goals ----
@app.get("/api/goals")
def list_goals(user: User = Depends(get_user), db: Session = Depends(get_db)):
    gs = db.query(Goal).filter_by(user_id=user.id).all()
    return [{"id":g.id,"title":g.title,"role_target":g.role_target,"timeline_months":g.timeline_months,"status":g.status} for g in gs]

@app.post("/api/goals")
def add_goal(req: GoalReq, user: User = Depends(get_user), db: Session = Depends(get_db)):
    g = Goal(user_id=user.id, title=f"Become {req.role_target}", role_target=req.role_target, timeline_months=req.timeline_months)
    user.target_role = req.role_target
    db.add(g); db.commit(); db.refresh(g)
    return {"ok":True,"id":g.id}

@app.delete("/api/goals/{gid}")
def del_goal(gid: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    g = db.query(Goal).filter_by(id=gid, user_id=user.id).first()
    if g: db.delete(g); db.commit()
    return {"ok":True}

# ---- Opportunities ----
@app.get("/api/opportunities")
def list_opportunities(user: User = Depends(get_user), db: Session = Depends(get_db), limit: int = 50, fit: bool = True):
    ops = db.query(Opportunity).limit(limit).all()
    user_skills = {s.name.lower() for s in db.query(Skill).filter_by(user_id=user.id).all()}
    interactions = {(i.opportunity_id, i.action) for i in db.query(OpportunityInteraction).filter_by(user_id=user.id).all()}
    saved = {oid for oid,a in interactions if a=="save"}
    applied = {oid for oid,a in interactions if a=="apply"}
    results = []
    for o in ops:
        req_skills = set(json.loads(o.skills_required or '[]'))
        gained = json.loads(o.skills_gained or '[]')
        match = len(req_skills & user_skills) / max(len(req_skills),1)
        # year eligibility filter (loose)
        eligible = True
        results.append({
            "id":o.id,"title":o.title,"type":o.type,"organizer":o.organizer,"description":o.description,
            "location":o.location,"stipend":o.stipend,"deadline":o.deadline,"url":o.url,
            "skills_required":list(req_skills),"skills_gained":gained,"difficulty":o.difficulty,
            "time_commitment":o.time_commitment,"fit_score":int(match*100),
            "saved": o.id in saved, "applied": o.id in applied
        })
    # Sort: matching skills first, then difficulty appropriate
    results.sort(key=lambda x: -x["fit_score"])
    return results

@app.post("/api/opportunities/{oid}/interact")
def interact(oid: str, payload: dict = Body(...), user: User = Depends(get_user), db: Session = Depends(get_db)):
    action = payload.get("action")
    if action not in ("view","save","apply","reject"):
        raise HTTPException(400, "Invalid action")
    i = OpportunityInteraction(user_id=user.id, opportunity_id=oid, action=action)
    db.add(i); db.commit()
    return {"ok":True}

# ---- Skill Gap Analysis ----
@app.post("/api/skills/analyze")
def analyze_skills(user: User = Depends(get_user), db: Session = Depends(get_db)):
    key = require_key(user)
    ctx = build_user_context(user, db)
    prompt = f"""You are MENTAURI's Skill Gap Intelligence. Given this student's profile (skills, projects, goals, personality), return a JSON object with:
{{
  "current_inventory": [list of strings - confirmed strengths you can infer from the profile],
  "missing_skills": [array of 8-12 specific skills ordered by leverage (most unlock value first) - e.g. "SQL", "System Design Basics", not vague like "communication"],
  "recommended_projects": [
    {{"title": string, "description": string (2-3 sentences exactly what to build), "skills_practiced": [string], "estimated_hours": number, "opportunities_unlocked": [strings - specific types of roles/opportunities this project opens]}}
  ] (3 starter-to-intermediate projects),
  "learning_roadmap": [
    {{"phase": "Weeks 1-4", "focus": string, "tasks": [strings]}},
    {{"phase": "Weeks 5-8", "focus": string, "tasks": [strings]}},
    {{"phase": "Weeks 9-12", "focus": string, "tasks": [strings]}}
  ],
  "estimated_prep_weeks": number,
  "key_insight": string (one blunt, honest, encouraging sentence about the single highest-leverage skill move for this person right now)
}}
Be specific. Don't say "learn programming" or "improve skills" - say exactly what, in whatever field actually fits this student's profile and goals (this may be engineering, medicine, civil services, law, management/consulting, academia, or any other field — do not default to tech skills unless the student's actual target role is technical). If they have a target role, tailor everything to that role. If not, tailor to their strengths.

Student profile: {ctx}
Return ONLY valid JSON."""
    try:
        result = call_gemini(key, prompt, temperature=0.6)
    except GeminiQuotaExceeded:
        result = {"error": "AI quota reached — showing general starter guidance instead.", "error_type": "quota_exceeded", "fallback": True,
                  "missing_skills": ["Structured writing","Time management","Domain fundamentals for your target field","Public speaking","Networking"],
                  "recommended_projects":[{"title":"A focused 30-day project in your target field","description":"Pick one small, real deliverable in your target field (a write-up, a mock case, a practice exam attempt, a small build — whatever fits) and finish it end-to-end within 30 days.","skills_practiced":["Follow-through","Domain fundamentals","Self-assessment"],"estimated_hours":20,"opportunities_unlocked":["Portfolio piece","Interview talking point"]}],
                  "learning_roadmap":[{"phase":"Weeks 1-4","focus":"Foundations","tasks":["Identify the 2-3 core skills your target field actually rewards","Find one credible source (course, mentor, or exam syllabus) and start it"]}],"estimated_prep_weeks":12,"key_insight":"Pick one skill that matters most for your specific goal and one small project — finishing that will move your momentum score more than reading ten guides."}
    except Exception as e:
        result = {"error": "Couldn't reach the AI right now — showing general starter guidance instead.", "fallback": True,
                  "missing_skills": ["Structured writing","Time management","Domain fundamentals for your target field","Public speaking","Networking"],
                  "recommended_projects":[{"title":"A focused 30-day project in your target field","description":"Pick one small, real deliverable in your target field (a write-up, a mock case, a practice exam attempt, a small build — whatever fits) and finish it end-to-end within 30 days.","skills_practiced":["Follow-through","Domain fundamentals","Self-assessment"],"estimated_hours":20,"opportunities_unlocked":["Portfolio piece","Interview talking point"]}],
                  "learning_roadmap":[{"phase":"Weeks 1-4","focus":"Foundations","tasks":["Identify the 2-3 core skills your target field actually rewards","Find one credible source (course, mentor, or exam syllabus) and start it"]}],"estimated_prep_weeks":12,"key_insight":"Pick one skill that matters most for your specific goal and one small project — finishing that will move your momentum score more than reading ten guides."}
    return result

# ---- Atlas Simulator ----
@app.post("/api/simulate")
def simulate_path(payload: dict = Body(...), user: User = Depends(get_user), db: Session = Depends(get_db)):
    key = require_key(user)
    target = payload.get("role_target") or user.target_role or "Software Engineer"
    timeline = int(payload.get("timeline_months", 12))
    ctx = build_user_context(user, db)
    prompt = f"""You are MENTAURI's Atlas Simulator. The user wants to become a **{target}** in roughly {timeline} months.
Generate 3 distinct realistic paths they could pursue, given their starting profile. Return ONLY JSON:
{{
  "goal": "{target}",
  "timeline_months": {timeline},
  "paths": [
    {{
      "name": string (catchy path name, e.g. "Industry Fast-Track"),
      "description": string (2 sentences),
      "suitable_for": string (who this is best for, referencing personality traits),
      "time_months": number,
      "difficulty": number (1-10, personalized — consider their starting skills),
      "steps": [{{"order":number,"title":string,"description":string,"duration_weeks":number,"action":string (specific action, not vague)}}],
      "skills_needed": [string],
      "outcomes": [string] (3 realistic outcomes — roles, salaries in INR per annum where relevant for India),
      "risks": [string] (2 honest risks),
      "exit_ramps": [string] (2 ways to pivot if this path stalls)
    }}
  ],
  "comparison_summary": string (one paragraph directly comparing the 3 paths for THIS specific student — which is safest, which is highest upside, which best matches their traits),
  "recommended_path_index": number (0, 1, or 2 — the index of the path you most recommend for this student, with a 1-sentence reason why)
}}

Student profile: {ctx}

This student's target may be in ANY field — engineering, medicine, civil services (UPSC/State PCS), law, consulting/management, academia, government, arts, or elsewhere. Tailor every path, step, and outcome specifically to the field implied by "{target}" — do not default to tech/software examples unless the target itself is tech-related. Be specific to India where relevant (real institutions, exams, or employers in THAT field — e.g. UPSC/State PCS for civil services, CAT/IIMs for management, NEET-PG/AIIMS for medicine, CLAT/NLUs for law, GATE/IITs for engineering — whichever actually fits the target). Be honest about competition levels but encouraging.
Return ONLY the JSON object."""
    try:
        result = call_gemini(key, prompt, temperature=0.7)
    except GeminiQuotaExceeded:
        result = {"goal":target,"timeline_months":timeline,"paths":[],"comparison_summary":"The AI is at its free quota limit right now — try the simulator again in a few minutes.","recommended_path_index":0}
    except Exception as e:
        result = {"goal":target,"timeline_months":timeline,"paths":[],"comparison_summary":"Couldn't run the simulation right now — try again shortly.","recommended_path_index":0}
    # cache
    sp = SimulationPath(user_id=user.id, goal_role=target, paths_json=json.dumps(result))
    db.add(sp); db.commit()
    return result

# ---- Checkins / Burnout / Momentum ----
@app.post("/api/checkin")
def post_checkin(req: CheckinReq, user: User = Depends(get_user), db: Session = Depends(get_db)):
    today = date.today()
    c = db.query(Checkin).filter_by(user_id=user.id, date=today).first()
    if not c:
        c = Checkin(user_id=user.id, date=today)
        db.add(c)
    c.energy = req.energy; c.productivity = req.productivity; c.hours_slept = req.hours_slept
    c.exercised = req.exercised; c.free_text = req.free_text
    db.commit()
    # recompute
    m = compute_momentum(user.id, db)
    b = compute_burnout(user.id, db)
    # store snapshots
    ms = db.query(MomentumSnapshot).filter_by(user_id=user.id, date=today).first()
    if not ms: ms = MomentumSnapshot(user_id=user.id, date=today); db.add(ms)
    ms.score = m["score"]; ms.components = json.dumps(m["components"])
    bs = db.query(BurnoutSnapshot).filter_by(user_id=user.id, date=today).first()
    if not bs: bs = BurnoutSnapshot(user_id=user.id, date=today); db.add(bs)
    bs.risk_score = b["risk_score"]; bs.band = b["band"]; bs.signals = json.dumps(b["signals"]); bs.recommendation = b["recommendation"]
    db.commit()
    return {"ok":True,"momentum":m,"burnout":b}

@app.get("/api/momentum/history")
def momentum_history(user: User = Depends(get_user), db: Session = Depends(get_db)):
    snaps = db.query(MomentumSnapshot).filter_by(user_id=user.id).order_by(MomentumSnapshot.date).limit(30).all()
    return [{"date":str(s.date),"score":s.score,"components":json.loads(s.components or '{}')} for s in snaps]

# ---- Daily Insights ----
@app.get("/api/insights/today")
def today_insights(user: User = Depends(get_user), db: Session = Depends(get_db)):
    key = require_key(user)
    ctx = build_user_context(user, db)
    hour = datetime.utcnow().hour + 5.5  # IST approx
    prompt = f"""You are MENTAURI — the user's AI mentor and coach. It is approximately {int(hour)} hours IST.
Given this user's full profile, generate today's personal briefing as JSON:
{{
  "greeting": string (personalized, uses their name, acknowledges time of day - morning/afternoon/evening),
  "one_priority_today": string (ONE concrete, small, achievable task that moves the needle most — not vague),
  "why_priority": string (1 sentence explaining why this specific thing matters given their goals),
  "energy_tip": string (1 actionable, evidence-based tip matching their current burnout band and recent energy),
  "opportunity_to_look_at": string (name of one specific kind of opportunity they should browse today - pick something genuinely matching their actual goal/field, which may be hackathons/internships/fellowships/research, OR exam prep, case interviews, MUN circuits, articleship, scholarships, etc. — whatever fits their profile, not assumed to be tech),
  "mindset_reminder": string (one short, warm, memorable sentence - like a sticky note from a wise mentor, not corporate fluff),
  "traction_score_forecast": number (0-100 - how much you estimate they can move their momentum today if they follow the priority, based on their recent pattern)
}}

User profile: {ctx}
Return ONLY JSON."""
    try:
        result = call_gemini(key, prompt, temperature=0.8)
    except Exception as e:
        result = {"greeting":f"Hey {user.name}!","one_priority_today":"Pick one 25-minute focused session on your most important goal and finish just the first step.","why_priority":"Starting is the hardest part; a small win creates momentum.","energy_tip":"Drink 2 glasses of water and step outside for 5 minutes of sun — it resets focus more reliably than coffee.","opportunity_to_look_at":"The Opportunity Atlas for programs matching your goals and timeline.","mindset_reminder":"You don't need a perfect day — you need one next action.","traction_score_forecast":40}
    return result

# ---- Mentaur Chat ----
@app.get("/api/chat/history")
def chat_history(user: User = Depends(get_user), db: Session = Depends(get_db)):
    msgs = db.query(ChatMessage).filter_by(user_id=user.id).order_by(ChatMessage.created_at).limit(50).all()
    return [{"role":m.role,"content":m.content,"created_at":m.created_at.isoformat()} for m in msgs]

@app.post("/api/chat")
def chat(req: ChatReq, user: User = Depends(get_user), db: Session = Depends(get_db)):
    key = require_key(user)
    msg = req.message.strip()
    if not msg:
        raise HTTPException(400,"empty")
    # Save user message
    u = ChatMessage(user_id=user.id, role="user", content=msg); db.add(u)
    # Load last 12 messages for context window
    history = db.query(ChatMessage).filter_by(user_id=user.id).order_by(ChatMessage.created_at.desc()).limit(12).all()
    history = list(reversed(history))
    ctx = build_user_context(user, db)
    sys = f"""You are MENTAURI ("Mentaur") — a warm, sharp, compassionate AI mentor and Human Potential Navigator built for Indian college students.
Your tone is like a wise senior who has walked the path — direct but kind, never preachy, occasionally witty. You reply in concise paragraphs (no walls of text), use emojis sparingly but warmly.
You always remember this student's specific profile (below). Reference their traits, goals, and state naturally — don't be robotic about it.

You help students with:
1. Figuring out WHAT to focus on next (cut through overwhelm)
2. Career path decisions (job vs MS vs startup vs research)
3. Personalized productivity advice (respect their energy and traits)
4. Skill development and project ideas
5. Mental health / burnout early intervention (be gentle, if serious risk suggest iCall 9152987821 or Vandrevala 1860-2662-345 — these are real Indian helplines)
6. Opportunity recommendations (hackathons, internships, fellowships, research)
7. Mock interviews and resume feedback (when asked)

Rules:
- Suggestive NOT authoritative. Present options, don't command.
- Be specific to India (mention Indian colleges, companies, exams, paths when relevant).
- If you don't know something, say so. Never make up facts about programs/companies/salaries.
- Keep replies under 200 words unless the user asked for a long answer.
- If the user is asking about a mental health crisis, take it seriously and provide helpline numbers.

Current student data:
{ctx}

Speak in the user's language (English by default; if they write in Hinglish or other Indian languages, reply in a mix matching them)."""

    # Build conversation contents for Gemini
    contents = [types.Content(parts=[types.Part.from_text(text="SYSTEM: "+sys)], role="user"),
                types.Content(parts=[types.Part.from_text(text="Understood. I am MENTAURI. Ready to help this student.")], role="model")]
    for h in history[-10:]:  # last 10 turns
        contents.append(types.Content(parts=[types.Part.from_text(text=h.content)], role=h.role if h.role in ("user","model") else "user"))
    contents.append(types.Content(parts=[types.Part.from_text(text=msg)], role="user"))

    try:
        client = get_gemini_client(key)
        cfg = types.GenerateContentConfig(temperature=0.85)
        resp = _generate_with_fallback(client, contents, cfg)
        reply = resp.text.strip()
    except GeminiQuotaExceeded:
        reply = ("I'm getting a lot of questions right now and have hit my free quota for the moment. "
                  "This usually clears up within a few minutes to a day — try again shortly, or add your "
                  "own free Gemini key in Settings so your chats aren't sharing the queue with everyone else.")
    except Exception as e:
        reply = "I'm having trouble thinking right now. Try again in a moment, or try restarting with a fresh question."
    a = ChatMessage(user_id=user.id, role="model", content=reply); db.add(a)
    db.commit()
    return {"reply": reply}

# ---- Resume/GitHub parse ----
@app.post("/api/import/resume")
async def import_resume(file: UploadFile = File(...), user: User = Depends(get_user), db: Session = Depends(get_db)):
    try:
        from PyPDF2 import PdfReader
        content = await file.read()
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)[:6000]
    except Exception as e:
        return {"error": f"Could not parse PDF: {e}", "skills": []}
    key = user.gemini_api_key or DEV_MODE_ENV_KEY
    if key:
        try:
            prompt = f"""Extract a structured JSON object from this resume text. Return:
{{"name":string,"email":string,"skills":[string array of specific technical/soft skills found in the resume],"projects":[{{"title":string,"description":string,"tech_stack":[string]}}],"education":string}}
Return ONLY JSON. Resume text: {text[:5000]}"""
            result = call_gemini(key, prompt, temperature=0.2)
            # add skills to user
            for sk in result.get("skills", [])[:20]:
                if not db.query(Skill).filter_by(user_id=user.id, name=sk).first():
                    db.add(Skill(user_id=user.id, name=sk, level="intermediate", source="resume"))
            for p in result.get("projects", [])[:5]:
                db.add(Project(user_id=user.id, title=p.get("title","Project"), description=p.get("description",""),
                              tech_stack=json.dumps(p.get("tech_stack",[])), url=""))
            db.commit()
            return {"ok":True,"extracted":result}
        except GeminiQuotaExceeded:
            return {"ok":False, "error": "The AI is at its free quota limit right now — try again in a few minutes, or add your own key in Settings.", "error_type": "quota_exceeded", "raw_preview": text[:500]}
        except Exception as e:
            return {"ok":False,"error":"Could not analyze the resume right now. Try again shortly.","raw_preview":text[:500]}
    return {"ok":False,"error":"No Gemini key - saved raw text","preview":text[:500]}

@app.post("/api/import/github")
async def import_github(payload: dict = Body(...), user: User = Depends(get_user), db: Session = Depends(get_db)):
    username = payload.get("username","").strip().replace("https://github.com/","").replace("/","")
    if not username:
        raise HTTPException(400, "username required")
    user.github_url = f"https://github.com/{username}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"https://api.github.com/users/{username}/repos?sort=updated&per_page=10")
            repos = r.json()
            if isinstance(repos, dict) and repos.get("message"):
                return {"ok":False,"error":repos["message"]}
            for repo in repos[:6]:
                lang = repo.get("language") or "Unknown"
                name = repo.get("name")
                desc = repo.get("description") or f"{lang} project"
                url = repo.get("html_url")
                # avoid duplicates
                existing = db.query(Project).filter_by(user_id=user.id, url=url).first()
                if existing: continue
                tech = [lang] if lang != "Unknown" else []
                if repo.get("topics"):
                    tech.extend(repo["topics"][:4])
                db.add(Project(user_id=user.id, title=name, description=desc, tech_stack=json.dumps(tech[:5]), url=url,
                              completed=not repo.get("fork")))
            # also infer language skills
            langs = set()
            for repo in repos:
                if repo.get("language") and repo["language"] not in ("Unknown",None):
                    langs.add(repo["language"])
            for L in langs:
                if not db.query(Skill).filter_by(user_id=user.id, name=L).first():
                    db.add(Skill(user_id=user.id, name=L, level="intermediate", source="github"))
            db.commit()
            return {"ok":True,"repos_imported":min(6,len(repos)),"languages":list(langs)}
    except Exception as e:
        return {"ok":False,"error":str(e)}

# ---- Todos ----
@app.get("/api/todos")
def list_todos(user: User = Depends(get_user), db: Session = Depends(get_db)):
    todos = db.query(Todo).filter_by(user_id=user.id).order_by(Todo.completed, Todo.created_at.desc()).all()
    return [{
        "id": t.id, "title": t.title, "category": t.category, "priority": t.priority,
        "completed": t.completed, "due_date": str(t.due_date) if t.due_date else None,
        "linked_opportunity_id": t.linked_opportunity_id,
        "created_at": t.created_at.isoformat(), "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    } for t in todos]

@app.post("/api/todos")
def add_todo(req: TodoReq, user: User = Depends(get_user), db: Session = Depends(get_db)):
    due = None
    if req.due_date:
        try:
            due = datetime.strptime(req.due_date, "%Y-%m-%d").date()
        except Exception:
            due = None
    t = Todo(
        user_id=user.id, title=req.title.strip(), category=req.category, priority=req.priority,
        due_date=due, linked_opportunity_id=req.linked_opportunity_id,
    )
    db.add(t); db.commit(); db.refresh(t)
    # Recompute momentum snapshot
    m = compute_momentum(user.id, db)
    return {"ok":True, "id": t.id, "todo": {
        "id": t.id, "title": t.title, "category": t.category, "priority": t.priority,
        "completed": False, "due_date": str(t.due_date) if t.due_date else None,
        "linked_opportunity_id": t.linked_opportunity_id,
    }, "momentum": m}

@app.patch("/api/todos/{tid}")
def update_todo(tid: str, req: TodoUpdate, user: User = Depends(get_user), db: Session = Depends(get_db)):
    t = db.query(Todo).filter_by(id=tid, user_id=user.id).first()
    if not t:
        raise HTTPException(404, "Todo not found")
    data = req.dict(exclude_unset=True)
    if "due_date" in data:
        dv = data.pop("due_date")
        t.due_date = datetime.strptime(dv, "%Y-%m-%d").date() if dv else None
    if "completed" in data:
        t.completed = data["completed"]
        t.completed_at = datetime.utcnow() if data["completed"] else None
    for k, v in data.items():
        setattr(t, k, v)
    db.commit()
    m = compute_momentum(user.id, db)
    return {"ok":True, "todo": {
        "id": t.id, "title": t.title, "category": t.category, "priority": t.priority,
        "completed": t.completed, "due_date": str(t.due_date) if t.due_date else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }, "momentum": m}

@app.delete("/api/todos/{tid}")
def delete_todo(tid: str, user: User = Depends(get_user), db: Session = Depends(get_db)):
    t = db.query(Todo).filter_by(id=tid, user_id=user.id).first()
    if t:
        db.delete(t); db.commit()
    return {"ok":True}

@app.post("/api/todos/suggest")
def suggest_todos(user: User = Depends(get_user), db: Session = Depends(get_db)):
    """Use Gemini to generate 5 personalized todos based on user profile + goals + skills."""
    key = require_key(user)
    ctx = build_user_context(user, db)
    prompt = f"""You are MENTAURI's action generator. Given this student's full profile, return a JSON object with 5 specific, small, concrete next-step todos they can take THIS WEEK. Mix categories: skill-building, opportunity actions, project tasks, wellbeing, networking. Return ONLY JSON:
{{
  "todos": [
    {{"title": string (specific action tailored to THIS student's actual field and goal — e.g. for a tech goal: 'Finish DSA arrays section on LeetCode (10 problems)'; for UPSC: 'Complete 1 full-length Prelims mock test and review errors'; for MBA: 'Solve 2 CAT DILR sets under timed conditions' — never generic like 'study more'), "category": one of ['skill','opportunity','project','wellbeing','networking'], "priority": one of ['low','medium','high'], "due_days_from_today": number (0-7)}}
  ],
  "why": string (2-3 sentences explaining how these connect to their profile)
}}
Student profile: {ctx}
Return ONLY valid JSON. Be specific to Indian context if applicable. Make each todo SHORT (under 80 chars) and DOABLE in one sitting."""
    try:
        result = call_gemini(key, prompt, temperature=0.8)
        todos = result.get("todos", [])
        created = []
        from datetime import timedelta
        for td in todos:
            due = date.today() + timedelta(days=int(td.get("due_days_from_today", 3)))
            t = Todo(
                user_id=user.id, title=td.get("title","").strip()[:200],
                category=td.get("category","general"),
                priority=td.get("priority","medium"),
                due_date=due,
            )
            db.add(t)
        db.commit()
        return {"ok":True, "todos_created": len(todos), "why": result.get("why",""), "todos": todos}
    except GeminiQuotaExceeded:
        return {"ok":False, "error": "The AI is at its free quota limit right now — try again in a few minutes, or add your own key in Settings.", "error_type": "quota_exceeded"}
    except Exception as e:
        return {"ok":False, "error": "Could not generate tasks right now. Try again shortly."}

# ---- Streak / Leaderboard ----
@app.get("/api/streak")
def get_streak(user: User = Depends(get_user), db: Session = Depends(get_db)):
    current = compute_streak(user.id, db)
    longest = longest_streak(user.id, db)
    total_checkins = db.query(Checkin).filter_by(user_id=user.id).count()
    # Last 30 days calendar
    from datetime import timedelta
    today = date.today()
    cal = []
    checkin_dates = {c.date for c in db.query(Checkin).filter_by(user_id=user.id).all()}
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        cal.append({"date": str(d), "checked": d in checkin_dates})
    return {"current_streak": current, "longest_streak": longest, "total_checkins": total_checkins, "calendar": cal}

def _public_name(u: User) -> str:
    """Make a privacy-preserving display name for leaderboard."""
    if not u.name:
        return "Anonymous Navigator"
    parts = u.name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1][0]}."
    return parts[0]

@app.get("/api/leaderboard")
def get_leaderboard(user: User = Depends(get_user), db: Session = Depends(get_db)):
    """Public leaderboard ranked by momentum score, with streak + tasks completed tiebreakers."""
    users = db.query(User).all()
    rows = []
    for u in users:
        m = compute_momentum(u.id, db)
        streak = compute_streak(u.id, db)
        todos_done = db.query(Todo).filter_by(user_id=u.id, completed=True).count()
        opps_saved = db.query(OpportunityInteraction).filter_by(user_id=u.id, action="save").count()
        onboarding_badge = "🧭" if u.onboarding_completed else ""
        streak_badge = "🔥" if streak >= 7 else ("✨" if streak >= 3 else "")
        rows.append({
            "user_id": u.id,
            "name": _public_name(u),
            "college": u.college or "",
            "target_role": u.target_role or "",
            "momentum": m["score"],
            "streak": streak,
            "todos_done": todos_done,
            "opps_saved": opps_saved,
            "badges": "".join(b for b in [onboarding_badge, streak_badge] if b),
            "is_me": u.id == user.id,
        })
    # Sort: momentum desc, streak desc, todos_done desc
    rows.sort(key=lambda r: (-r["momentum"], -r["streak"], -r["todos_done"]))
    # Assign ranks
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    me_row = next((r for r in rows if r["is_me"]), None)
    # Return top 20 + neighborhood around user
    top = rows[:20]
    if me_row and me_row["rank"] > 20:
        # include 2 above + 2 below me if they exist and aren't already in top
        me_idx = next(i for i, r in enumerate(rows) if r["is_me"])
        neighborhood = rows[max(0, me_idx-2):me_idx+3]
        # merge avoiding duplicates
        seen = {r["user_id"] for r in top}
        for r in neighborhood:
            if r["user_id"] not in seen:
                top.append(r)
    return {
        "leaderboard": top,
        "me": me_row,
        "total_users": len(rows),
        "updated_at": datetime.utcnow().isoformat(),
    }

# ---- Nudge for welcome ----
@app.get("/api/welcome")
def welcome(user: User = Depends(get_user), db: Session = Depends(get_db)):
    if not user.onboarding_completed:
        return {"stage":"onboarding","message":f"Hey {user.name}, let's start with the personality assessment to map your potential."}
    key = user.gemini_api_key or DEV_MODE_ENV_KEY
    if not key:
        return {"stage":"need_key","message":"Add your Gemini API key to unlock AI features."}
    return {"stage":"ready"}

print("Routes registered")

import streamlit as st
import pandas as pd
import sqlite3, urllib.parse, requests, re, io, xml.etree.ElementTree as ET
from datetime import date, datetime
from html.parser import HTMLParser

st.set_page_config(page_title="AI求职助手 v2.0", page_icon="🎯", layout="wide")
DB="jobs_v2.db"
COMPANY_FILE="companies.csv"
PROFILE={"cities":["深圳","广州","上海"],"degree":"本科应届生","major":"应用化学","keywords":["化学分析","分析检测","QC","质量","实验员","实验技术员","研究助理","应用工程师","技术支持","工艺工程师","工艺技术员","材料","化工","半导体","新能源","医药","配方"]}
SEARCH_TERMS=["化学分析","分析检测","QC质量","实验员","研究助理 化学","应用工程师 化学","技术支持 化学","工艺技术员 化学","材料 化学","新能源 化学","半导体 化学","医药 QC","配方研发 化学"]
STATUS_OPTIONS=["待筛选","准备投递","已投递","笔试","面试","待回复","已录用","已拒绝","已放弃"]

class DDGParser(HTMLParser):
    def __init__(self): super().__init__(); self.items=[]; self.cur=None; self.capture=None; self.buf=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs); cls=a.get("class","")
        if tag=="a" and "result__a" in cls:
            self.cur={"title":"","url":a.get("href",""),"snippet":""}; self.capture="title"; self.buf=[]
        elif self.cur and tag in ("div","a") and "result__snippet" in cls:self.capture="snippet"; self.buf=[]
    def handle_data(self,data):
        if self.capture:self.buf.append(data)
    def handle_endtag(self,tag):
        if self.capture and tag in ("a","div"):
            val=" ".join(" ".join(self.buf).split())
            if self.capture=="title" and self.cur:self.cur["title"]=val
            elif self.capture=="snippet" and self.cur:self.cur["snippet"]=val
            self.capture=None; self.buf=[]
            if self.cur and self.cur.get("title"):self.items.append(self.cur); self.cur=None

def connect():
    c=sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS companies(id INTEGER PRIMARY KEY, city TEXT, company TEXT, target_roles TEXT, priority TEXT, industry TEXT, recruiting_evidence TEXT, notes TEXT, official_url TEXT, last_checked TEXT, check_status TEXT DEFAULT '未检查', UNIQUE(city,company))")
    c.execute("CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,url TEXT UNIQUE,snippet TEXT,city TEXT,company TEXT,query TEXT,source TEXT,match_score INTEGER,fit_reasons TEXT,risk_flags TEXT,found_at TEXT DEFAULT CURRENT_TIMESTAMP,review_status TEXT DEFAULT '待筛选')")
    c.execute("CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,company TEXT,role TEXT,city TEXT,degree TEXT,major TEXT,experience TEXT,salary TEXT,status TEXT,url TEXT,description TEXT,match_score INTEGER,apply_status TEXT,applied_date TEXT,notes TEXT,source TEXT,UNIQUE(company,role,city,url))")
    c.commit(); return c

def seed_companies():
    c=connect()
    try:
        df=pd.read_csv(COMPANY_FILE).fillna("")
        for _,r in df.iterrows():
            c.execute("INSERT OR IGNORE INTO companies(city,company,target_roles,priority,industry,recruiting_evidence,notes) VALUES(?,?,?,?,?,?,?)",tuple(str(r[k]) for k in ['city','company','target_roles','priority','industry','recruiting_evidence','notes']))
        c.commit()
    except Exception as e: st.error(f"企业名单初始化失败：{e}")
    c.close()

def score_text(title,snippet,city):
    text=(str(title)+" "+str(snippet)).lower(); score=20; reasons=[]; risks=[]
    matches=[k for k in PROFILE['keywords'] if k.lower() in text]
    if matches: score+=min(30,8+3*len(matches)); reasons.append('岗位方向关键词：'+','.join(matches[:6]))
    else: risks.append('岗位方向关联不明确')
    if any(k in text for k in ['本科','应届','校招','毕业生','无经验','不限经验']):score+=20; reasons.append('本科/应届线索')
    else:risks.append('学历/应届要求待核实')
    if any(k in text for k in ['应用化学','分析化学','化学专业','化学类','材料','化工']):score+=20;reasons.append('化学/材料专业线索')
    hard_degree=any(k in text for k in ['博士研究生','博士及以上','硕士研究生','硕士及以上','研究生及以上'])
    hard_exp=any(k in text for k in ['3年以上工作经验','3年及以上经验','5年以上工作经验','5年及以上经验'])
    if hard_degree:score-=35;risks.append('可能要求硕士/博士')
    if hard_exp:score-=25;risks.append('可能要求多年经验')
    if any(k in text for k in ['招聘信息汇总','职位搜索','招聘大全','招聘网']):risks.append('可能为聚合页，不一定是具体岗位')
    score=max(0,min(100,score))
    if hard_degree or hard_exp:score=min(score,49)
    return score,'；'.join(reasons) or '信息不足','；'.join(risks) or '未发现明显风险词，仍需打开原页面核实'

def search_web(query,max_results=8):
    headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'}
    out=[]; seen=set(); engine='DuckDuckGo'
    try:
        url='https://html.duckduckgo.com/html/?q='+urllib.parse.quote(query)
        r=requests.get(url,headers=headers,timeout=18);r.raise_for_status();p=DDGParser();p.feed(r.text)
        for x in p.items:
            if x['url'] and x['url'] not in seen:seen.add(x['url']);out.append(x)
    except Exception:pass
    if not out:
        try:
            rss='https://www.bing.com/search?format=rss&q='+urllib.parse.quote(query)
            rr=requests.get(rss,headers=headers,timeout=18);rr.raise_for_status();root=ET.fromstring(rr.text)
            for item in root.findall('.//item'):
                x={'title':item.findtext('title') or '', 'url':item.findtext('link') or '', 'snippet':item.findtext('description') or ''}
                if x['url'] and x['url'] not in seen:seen.add(x['url']);out.append(x)
            engine='Bing RSS备用'
        except Exception:pass
    return [{**x,'source':engine} for x in out[:max_results]]

def get_companies():
    c=connect();df=pd.read_sql_query('SELECT * FROM companies ORDER BY city,priority,company',c);c.close();return df

def get_candidates():
    c=connect();df=pd.read_sql_query('SELECT * FROM candidates ORDER BY match_score DESC,found_at DESC',c);c.close();return df

def get_jobs():
    c=connect();df=pd.read_sql_query('SELECT * FROM jobs ORDER BY match_score DESC,id DESC',c);c.close();return df

def save_candidate(rows):
    c=connect()
    for x in rows:
        score,reason,risk=score_text(x['title'],x['snippet'],x['city'])
        c.execute('''INSERT INTO candidates(title,url,snippet,city,company,query,source,match_score,fit_reasons,risk_flags)
        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title,snippet=excluded.snippet,city=excluded.city,company=excluded.company,query=excluded.query,source=excluded.source,match_score=excluded.match_score,fit_reasons=excluded.fit_reasons,risk_flags=excluded.risk_flags''',
        (x['title'],x['url'],x['snippet'],x['city'],x['company'],x['query'],x['source'],score,reason,risk))
    c.commit();c.close()

def save_job(row):
    c=connect(); role=row['title']
    c.execute('INSERT OR IGNORE INTO jobs(company,role,city,degree,major,experience,salary,status,url,description,match_score,apply_status,notes,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
    (row['company'],role,row['city'],'待核实','应用化学/相关专业（待核实）','待核实','待核实','待核实',row['url'],row['snippet'],row['match_score'],'待筛选','来源候选，打开原页面核实','企业监控搜索'))
    c.commit();c.close()

seed_companies()
st.title('🎯 AI求职助手 · v2.0 企业监控版')
st.caption('100家目标企业｜深圳·广州·上海｜企业定向搜索｜候选去重｜岗位匹配｜人工确认投递')
with st.sidebar:
 st.header('求职目标')
 st.write('学历：本科应届生｜专业：应用化学')
 st.write('城市：深圳 / 广州 / 上海')
 st.write('方向：分析检测、QC/质量、实验室、应用技术、工艺、材料、医药、新能源、半导体')
 st.warning('搜索结果为公开网页候选线索，不能保证招聘仍开放。申请提交仍由本人确认。')
companies=get_companies(); candidates=get_candidates(); jobs=get_jobs()
col1,col2,col3,col4=st.columns(4)
col1.metric('目标企业',len(companies));col2.metric('发现候选',len(candidates));col3.metric('待筛选岗位',int((jobs.get('apply_status',pd.Series(dtype=str))=='待筛选').sum()) if len(jobs) else 0);col4.metric('已投递',int((jobs.get('apply_status',pd.Series(dtype=str))=='已投递').sum()) if len(jobs) else 0)
tabs=st.tabs(['🏠 工作台','🏢 企业库/监控','🔎 定向搜索','🎯 候选岗位队列','📌 投递管理','📥 导入导出'])

with tabs[0]:
 st.subheader('目标企业概览')
 if len(companies):
  st.dataframe(companies.groupby(['city','priority']).size().unstack(fill_value=0),use_container_width=True)
 st.subheader('高匹配候选岗位')
 if len(candidates):st.dataframe(candidates[['company','city','title','match_score','review_status','source','url']].head(30),use_container_width=True,hide_index=True)
 else:st.info('还没有监控搜索结果。到“定向搜索”先搜索一批企业。')
 st.info('推荐开始方式：先搜索A优先级企业，每批5家，避免一次搜索过多导致等待或搜索源限制。')

with tabs[1]:
 st.subheader('100家企业库')
 ccity=st.multiselect('按城市查看',PROFILE['cities'],default=PROFILE['cities'],key='company_city_filter')
 pr=st.multiselect('优先级', ['A','B','C'],default=['A','B','C'],key='company_priority_filter')
 view=companies[companies.city.isin(ccity)&companies.priority.isin(pr)]
 st.dataframe(view[['city','company','priority','industry','target_roles','recruiting_evidence','official_url','last_checked','check_status','notes']],use_container_width=True,hide_index=True)
 st.caption('可在下方编辑公司招聘官网链接；初始企业名单来自你此前的100家公司清单。')
 if len(view):
  editid=st.selectbox('选择要补充招聘官网链接的企业',view.apply(lambda r:f"{r.city}｜{r.company}",axis=1))
  er=view[view.apply(lambda r:f"{r.city}｜{r.company}"==editid,axis=1)].iloc[0]
  with st.form('edit_company'):
   official=st.text_input('招聘官网/招聘页面URL',value=str(er.official_url or ''),placeholder='粘贴公司官网招聘链接')
   save=st.form_submit_button('保存招聘官网链接')
  if save:
   c=connect();c.execute('UPDATE companies SET official_url=? WHERE id=?',(official,int(er.id)));c.commit();c.close();st.success('已保存');st.rerun()

with tabs[2]:
 st.subheader('按目标企业定向搜索')
 fcity=st.multiselect('搜索城市',PROFILE['cities'],default=['深圳'],key='monitor_city')
 fpriority=st.multiselect('企业优先级', ['A','B','C'],default=['A'],key='monitor_priority')
 pool=companies[companies.city.isin(fcity)&companies.priority.isin(fpriority)]
 selected_companies=st.multiselect('选择本批企业（建议每次5家）',pool.company.tolist(),default=pool.company.tolist()[:5])
 role_terms=st.multiselect('岗位搜索方向',SEARCH_TERMS,default=['化学分析','分析检测','QC质量','实验员','应用工程师 化学'])
 per_company=st.slider('每家企业最多保留搜索结果',2,8,4)
 if st.button('🚀 开始本批企业搜索',type='primary'):
  batch=pool[pool.company.isin(selected_companies)]
  total=max(1,len(batch)*len(role_terms));counter=0;results=[];progress=st.progress(0)
  for _,co in batch.iterrows():
   for term in role_terms:
    counter+=1;progress.progress(counter/total)
    q=f"{co.company} {co.city} {term} 招聘 应届 本科"
    try:
     for x in search_web(q,per_company):
      # company-specific query result still requires verification; attach target company and city
      x.update({'city':co.city,'company':co.company,'query':q});results.append(x)
    except Exception as e:st.warning(f"暂时失败：{co.company} / {term} / {str(e)[:80]}")
  if results:
   save_candidate(results);c=connect()
   for _,co in batch.iterrows():c.execute("UPDATE companies SET last_checked=?,check_status='已搜索' WHERE id=?",(datetime.now().strftime('%Y-%m-%d %H:%M'),int(co.id)))
   c.commit();c.close();st.success(f'搜索完成：获得 {len(results)} 条候选线索。结果已保存并去重。');st.rerun()
  else:st.warning('没有返回候选结果。可能是搜索源限制或关键词无结果，可稍后重试。')
 st.caption('注意：搜索结果可能来自招聘平台或聚合页面，不一定是企业官方岗位。')

with tabs[3]:
 st.subheader('候选岗位筛选与待投递队列')
 if len(candidates):
  minscore=st.slider('最低匹配分数',0,100,50,key='candidate_score_filter')
  ccity=st.multiselect('候选城市',PROFILE['cities'],default=PROFILE['cities'],key='candidate_city_filter')
  review=candidates[(candidates.match_score>=minscore)&(candidates.city.isin(ccity))]
  st.dataframe(review[['id','company','city','title','match_score','fit_reasons','risk_flags','review_status','url']],use_container_width=True,hide_index=True)
  if len(review):
   opts={f"#{r.id}｜{r.company}｜{r.city}｜{r.title[:60]}｜{r.match_score}分":int(r.id) for _,r in review.iterrows()}
   choice=st.selectbox('选择岗位',list(opts))
   row=review[review.id==opts[choice]].iloc[0]
   st.write('**搜索摘要**');st.write(row.snippet)
   if row.url:st.link_button('打开原始招聘页面核实',row.url)
   action=st.radio('候选处理', ['加入待投递队列','标记不合适','标记已核实'],horizontal=True)
   if st.button('确认处理候选岗位'):
    c=connect()
    if action=='加入待投递队列':save_job(row.to_dict());c.execute("UPDATE candidates SET review_status='已加入队列' WHERE id=?",(int(row.id),))
    elif action=='标记不合适':c.execute("UPDATE candidates SET review_status='不合适' WHERE id=?",(int(row.id),))
    else:c.execute("UPDATE candidates SET review_status='已核实' WHERE id=?",(int(row.id),))
    c.commit();c.close();st.success('已更新');st.rerun()
 else:st.info('先到“定向搜索”进行企业搜索。')

with tabs[4]:
 st.subheader('投递跟踪')
 if len(jobs):
  st.dataframe(jobs[['company','role','city','match_score','status','apply_status','applied_date','url','notes']],use_container_width=True,hide_index=True)
  jopts={f"#{r.id}｜{r.company}｜{r.role[:50]}":int(r.id) for _,r in jobs.iterrows()};selected=st.selectbox('更新一条投递记录',list(jopts))
  r=jobs[jobs.id==jopts[selected]].iloc[0]
  with st.form('update_tracker'):
   newstatus=st.selectbox('投递状态',STATUS_OPTIONS,index=STATUS_OPTIONS.index(r.apply_status) if r.apply_status in STATUS_OPTIONS else 0)
   dt=st.date_input('投递日期',value=date.fromisoformat(r.applied_date) if r.applied_date and str(r.applied_date)[:10] not in ['', 'None'] else date.today())
   note=st.text_area('跟进记录',str(r.notes or ''))
   save=st.form_submit_button('保存状态')
  if save:
   c=connect();c.execute('UPDATE jobs SET apply_status=?,applied_date=?,notes=? WHERE id=?',(newstatus,dt.isoformat() if newstatus=='已投递' else (r.applied_date or ''),note,int(r.id)));c.commit();c.close();st.success('记录更新');st.rerun()
  if r.url:st.link_button('打开招聘页面',r.url)
 else:st.info('队列为空。先将候选岗位加入待投递队列。')

with tabs[5]:
 st.subheader('企业/岗位数据导入导出')
 st.write('企业库导出')
 st.download_button('下载企业库CSV',companies.to_csv(index=False).encode('utf-8-sig'),'companies_export.csv','text/csv')
 st.write('候选岗位导出')
 if len(candidates):st.download_button('下载候选岗位CSV',candidates.to_csv(index=False).encode('utf-8-sig'),'candidate_jobs.csv','text/csv')
 st.write('投递记录导出')
 if len(jobs):st.download_button('下载投递岗位CSV',jobs.to_csv(index=False).encode('utf-8-sig'),'job_tracker.csv','text/csv')
 upload=st.file_uploader('导入或更新企业库CSV（必须含city/company列）',type=['csv'])
 if upload:
  try:
   imp=pd.read_csv(upload).fillna('');st.dataframe(imp.head(),use_container_width=True)
   if st.button('确认导入企业库'):
    c=connect()
    for _,r in imp.iterrows():
     c.execute('INSERT OR IGNORE INTO companies(city,company,target_roles,priority,industry,recruiting_evidence,notes,official_url) VALUES(?,?,?,?,?,?,?,?)',tuple(str(r.get(k,'')) for k in ['city','company','target_roles','priority','industry','recruiting_evidence','notes','official_url']))
    c.commit();c.close();st.success('导入完成');st.rerun()
  except Exception as e:st.error(f'导入失败：{e}')

st.divider()
st.caption('v2.0 | 企业定向监控原型 | 搜索线索需人工核实 | 不自动提交申请 | SQLite云端持久化不保证，请定期导出备份。')

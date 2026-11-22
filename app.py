import streamlit as st
import pandas as pd
import sqlite3, json, os
from datetime import date

st.set_page_config(page_title='AI求职助手', page_icon='🎯', layout='wide')
DB='jobs.db'

PROFILE = {
    'cities':['深圳','广州','上海'],
    'degree':'本科应届生',
    'major':'应用化学',
    'roles':['化学分析','分析检测','QC','质量','实验员','实验技术员','研究助理','应用工程师','技术支持','工艺工程师','工艺技术员'],
    'keywords':['化学','应用化学','分析化学','材料','化工','检测','实验','QC','质量','工艺','技术支持','研发']
}

def connect():
    c=sqlite3.connect(DB)
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, role TEXT, city TEXT, degree TEXT, major TEXT,
      experience TEXT, salary TEXT, status TEXT, url TEXT, description TEXT, match_score INTEGER,
      apply_status TEXT, applied_date TEXT, notes TEXT, source TEXT)''')
    c.commit(); return c

def score_job(row):
    score=0
    city=str(row.get('city',''))
    if any(c in city for c in PROFILE['cities']): score+=25
    degree=str(row.get('degree','')).lower()
    if '本科' in degree or '大专' in degree or '不限' in degree: score+=20
    elif '硕士' in degree or '博士' in degree: score-=30
    major=str(row.get('major',''))
    if any(k in major for k in ['应用化学','化学','材料','化工','理工']): score+=20
    role=str(row.get('role',''))
    if any(k in role for k in ['分析','检测','QC','质量','实验','技术员','研究助理']): score+=20
    elif any(k in role for k in ['应用','技术支持','工艺']): score+=15
    exp=str(row.get('experience',''))
    if '应届' in exp or '无经验' in exp or '不限' in exp: score+=15
    elif '3年' in exp or '5年' in exp: score-=20
    return max(0,min(100,score))

def fetch():
    c=connect(); df=pd.read_sql_query('SELECT * FROM jobs ORDER BY match_score DESC, id DESC',c); c.close(); return df

def add_job(data):
    data['match_score']=score_job(data)
    c=connect()
    c.execute('INSERT INTO jobs(company,role,city,degree,major,experience,salary,status,url,description,match_score,apply_status,applied_date,notes,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      (data.get('company',''),data.get('role',''),data.get('city',''),data.get('degree',''),data.get('major',''),data.get('experience',''),data.get('salary',''),data.get('status','待核实'),data.get('url',''),data.get('description',''),data['match_score'],data.get('apply_status','待筛选'),data.get('applied_date',''),data.get('notes',''),data.get('source','手动录入')))
    c.commit(); c.close()

st.title('🎯 AI求职助手 · 第一版')
st.caption('面向应用化学本科应届生｜深圳 · 广州 · 上海｜半自动工作流，关键申请由本人确认')

with st.sidebar:
    st.header('求职条件')
    st.write('**城市：** 深圳、广州、上海')
    st.write('**学历：** 本科应届优先')
    st.write('**专业：** 应用化学及相关专业')
    st.write('**目标方向：** 化学分析、检测、QC、实验技术、应用技术、工艺')
    st.info('第一版不自动登录或提交招聘网站。岗位由手动录入/CSV导入，后续再增加合规的搜索与浏览器辅助功能。')

pages=st.tabs(['📊 工作台','➕ 添加岗位','📥 CSV导入','📋 投递管理','📝 简历与话术'])
with pages[0]:
    df=fetch()
    a,b,d=st.columns(3)
    a.metric('岗位总数',len(df))
    b.metric('待投递',int((df.apply_status=='待筛选').sum()) if len(df) else 0)
    d.metric('已投递',int((df.apply_status=='已投递').sum()) if len(df) else 0)
    if len(df):
        st.subheader('匹配度排名')
        st.dataframe(df[['company','role','city','degree','major','experience','salary','match_score','status','url','apply_status']],use_container_width=True,hide_index=True)
    else: st.info('还没有岗位。请先在“添加岗位”或“CSV导入”页面添加第一批招聘信息。')
with pages[1]:
    st.subheader('录入岗位信息')
    with st.form('job_form'):
        company=st.text_input('公司名称*'); role=st.text_input('岗位名称*'); city=st.selectbox('城市',['深圳','广州','上海','其他'])
        degree=st.text_input('学历要求',placeholder='本科及以上 / 本科 / 大专及以上')
        major=st.text_input('专业要求',placeholder='应用化学、化学、材料等')
        experience=st.text_input('经验要求',placeholder='应届 / 无经验 / 1-3年')
        salary=st.text_input('薪资'); status=st.selectbox('招聘状态',['待核实','招聘中','已截止','未知'])
        url=st.text_input('申请链接'); source=st.text_input('来源'); description=st.text_area('岗位描述/备注')
        submit=st.form_submit_button('保存岗位')
        if submit:
            if not company or not role: st.error('公司名称和岗位名称必须填写。')
            else:
                add_job(locals()); st.success(f'岗位已保存，自动匹配分：{score_job(locals())}分'); st.rerun()
with pages[2]:
    st.subheader('CSV批量导入')
    st.write('CSV列名建议：company, role, city, degree, major, experience, salary, status, url, description, source')
    template=pd.DataFrame(columns=['company','role','city','degree','major','experience','salary','status','url','description','source'])
    st.download_button('下载CSV模板',template.to_csv(index=False).encode('utf-8-sig'),'jobs_template.csv','text/csv')
    file=st.file_uploader('上传岗位CSV文件',type=['csv'])
    if file:
        imp=pd.read_csv(file).fillna('')
        st.dataframe(imp.head(20),use_container_width=True)
        if st.button('导入这些岗位'):
            for _,r in imp.iterrows(): add_job(r.to_dict())
            st.success(f'已导入 {len(imp)} 条'); st.rerun()
with pages[3]:
    st.subheader('投递跟踪')
    df=fetch()
    if len(df):
        selected=st.selectbox('选择岗位',df.apply(lambda r:f"#{r.id} {r.company}｜{r.role}｜{r.city}",axis=1))
        jid=int(selected.split(' ')[0][1:])
        row=df[df.id==jid].iloc[0]
        with st.form('update'):
            status=st.selectbox('投递状态',['待筛选','准备投递','已投递','笔试','面试','Offer','拒绝','已截止'],index=['待筛选','准备投递','已投递','笔试','面试','Offer','拒绝','已截止'].index(row.apply_status) if row.apply_status in ['待筛选','准备投递','已投递','笔试','面试','Offer','拒绝','已截止'] else 0)
            applied=st.date_input('投递日期',value=date.today() if row.applied_date=='' else pd.to_datetime(row.applied_date).date())
            notes=st.text_area('跟进记录',value=row.notes)
            if st.form_submit_button('更新记录'):
                c=connect(); c.execute('UPDATE jobs SET apply_status=?,applied_date=?,notes=? WHERE id=?',(status,applied.isoformat(),notes,jid));c.commit();c.close();st.success('更新成功');st.rerun()
        st.markdown('**申请链接**')
        if row.url: st.link_button('打开招聘页面',row.url)
        st.download_button('导出投递记录CSV',df.to_csv(index=False).encode('utf-8-sig'),'application_tracker.csv','text/csv')
    else: st.info('先添加岗位后才能跟踪。')
with pages[4]:
    st.subheader('简历与申请话术')
    resume=st.file_uploader('上传简历（仅当前运行环境处理；此版本不自动发送）',type=['docx','pdf'])
    st.write('**HR打招呼模板**')
    st.text_area('复制使用',value='您好，我是广东海洋大学应用化学专业本科应届毕业生，关注贵公司的【岗位名称】岗位。我的专业课程和实验实践涉及化学分析、样品前处理、实验数据记录及常见仪器操作，并有相关实习经历。希望有机会进一步沟通，谢谢！',height=150)
    st.warning('后续版本计划：岗位抓取/检索、AI匹配解释、简历多版本生成、浏览器辅助填写。所有关键个人信息和最终提交仍需你确认。')

st.divider(); st.caption('MVP v0.1｜数据保存在当前部署实例的SQLite数据库。部署到云端前，请注意数据隐私；不要上传身份证、银行卡等敏感信息。')

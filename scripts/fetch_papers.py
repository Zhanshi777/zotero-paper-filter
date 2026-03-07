import feedparser
import os
import json
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin
import re
import html
import requests
import openai
from bs4 import BeautifulSoup
import time

# ==================== 配置区域 ====================

FEEDS = {
    "Nature": "https://www.nature.com/nature.rss",
    "Nature Communications": "https://www.nature.com/ncomms.rss",
    "Science": "https://feeds.science.org/rss/science.xml",
    "Joule": "https://www.cell.com/joule/inpress.rss",
    "Nature Energy": "https://www.nature.com/nenergy.rss",
    "Nature Synthesis": "https://www.nature.com/natsynth.rss",
    "Energy & Environmental Science": "http://feeds.rsc.org/rss/ee",
    "Angewandte Chemie": "https://onlinelibrary.wiley.com/feed/15213773/most-recent",
    "Advanced Materials": "https://advanced.onlinelibrary.wiley.com/feed/15214095/most-recent",
    "Advanced Energy Materials": "https://advanced.onlinelibrary.wiley.com/feed/16146840/most-recent",
    "Advanced Functional Materials": "https://advanced.onlinelibrary.wiley.com/feed/16163028/most-recent"
}

KEYWORDS_ENV = os.environ.get('RESEARCH_KEYWORDS', 'perovskite')
KEYWORDS = [k.strip().lower() for k in KEYWORDS_ENV.split(',') if k.strip()]

DAYS_BACK = 3

API_KEY = os.environ.get('OPENAI_API_KEY', '')
BASE_URL = os.environ.get('OPENAI_BASE_URL', None)

ai_client = None
if API_KEY:
    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL
    ai_client = openai.OpenAI(**client_kwargs)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

# ==================== 核心函数 ====================

def clean_html(text):
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = html.unescape(clean)
    return clean.strip()

def extract_doi(entry):
    doi = ""
    if hasattr(entry, 'id'):
        doi_match = re.search(r'10\.\d{4,}/[^\s<>"\']+', entry.id)
        if doi_match:
            doi = doi_match.group(0)
    if not doi and hasattr(entry, 'link'):
        doi_match = re.search(r'10\.\d{4,}/[^\s<>"\']+', entry.link)
        if doi_match:
            doi = doi_match.group(0)
    if doi:
        doi = doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
    return doi

def get_download_links(paper):
    journal = paper['journal']
    doi = paper.get('doi', '')
    link = paper.get('link', '')
    pdf_url = None
    si_url = None
    
    if not doi and not link:
        return pdf_url, si_url
    
    try:
        if journal in ["Nature", "Nature Communications", "Nature Energy", "Nature Synthesis"]:
            if '/articles/' in link:
                article_id = link.split('/articles/')[-1].split('/')[0].split('?')[0]
                pdf_url = f"https://www.nature.com/articles/{article_id}.pdf"
                si_url = f"https://www.nature.com/articles/{article_id}#Sec20"
        
        elif journal == "Science":
            if doi:
                pdf_url = f"https://www.science.org/doi/pdf/{doi}"
                si_url = f"https://www.science.org/doi/suppl/{doi}"
        
        elif journal == "Joule":
            if '/article/pii/' in link:
                pii = link.split('/article/pii/')[-1].split('/')[0]
                pdf_url = f"https://www.cell.com/action/showPdf?pii={pii}"
                si_url = f"{link}#supplementary-materials"
            elif doi:
                pdf_url = f"https://doi.org/{doi}"
                si_url = f"https://doi.org/{doi}#supplementary-materials"
        
        elif journal == "Energy & Environmental Science":
            if doi:
                pdf_url = f"https://pubs.rsc.org/en/content/articlepdf/{doi}"
                si_url = f"https://pubs.rsc.org/en/content/articlesuppl/{doi}"
        
        elif journal in ["Angewandte Chemie", "Advanced Materials", 
                        "Advanced Energy Materials", "Advanced Functional Materials"]:
            if doi:
                pdf_url = f"https://onlinelibrary.wiley.com/doi/pdf/{doi}"
                si_url = f"https://onlinelibrary.wiley.com/doi/abs/{doi}#support-information-section"
    
    except Exception as e:
        print(f"构建下载链接出错: {e}")
    
    return pdf_url, si_url

def fetch_article_content(url, journal):
    """访问文章网页获取真实Abstract和Figures"""
    try:
        print(f"      🌐 爬取: {url[:70]}...")
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        abstract = ""
        figures = []
        
        # Nature系列
        if journal in ["Nature", "Nature Communications", "Nature Energy", "Nature Synthesis"]:
            abs_div = (soup.find('div', {'id': 'Abs1-content'}) or 
                      soup.find('div', class_='c-article-teaser__text') or
                      soup.find('div', class_='c-article__abstract'))
            if abs_div:
                abstract = clean_html(str(abs_div))
            
            figure_tags = soup.find_all('figure', limit=6)
            for i, fig in enumerate(figure_tags, 1):
                img = fig.find('img')
                caption = fig.find('figcaption')
                if img:
                    img_url = img.get('src', '')
                    if img_url.startswith('/'):
                        img_url = urljoin(url, img_url)
                    # 过滤掉太小的图标图片
                    if 'icon' not in img_url.lower() and 'logo' not in img_url.lower():
                        figures.append({
                            'number': str(i),
                            'url': img_url,
                            'caption': clean_html(str(caption))[:150] + "..." if caption else f"Figure {i}"
                        })
        
        # Wiley期刊
        elif journal in ["Angewandte Chemie", "Advanced Materials", 
                        "Advanced Energy Materials", "Advanced Functional Materials"]:
            abs_section = (soup.find('section', {'id': 'abstract'}) or 
                          soup.find('div', class_='article-section__abstract'))
            if abs_section:
                abstract = clean_html(str(abs_section))
            
            figure_divs = soup.find_all('div', class_='figure', limit=6)
            for i, fig in enumerate(figure_divs, 1):
                img = fig.find('img')
                caption = fig.find('div', class_='figure__caption')
                if img:
                    img_url = img.get('data-src', '') or img.get('src', '')
                    if img_url.startswith('/'):
                        img_url = urljoin(url, img_url)
                    figures.append({
                        'number': str(i),
                        'url': img_url,
                        'caption': clean_html(str(caption))[:150] + "..." if caption else f"Figure {i}"
                    })
        
        # Cell Press (Joule)
        elif journal == "Joule":
            abs_div = (soup.find('div', class_='abstract') or 
                      soup.find('section', {'id': 'abstract'}))
            if abs_div:
                abstract = clean_html(str(abs_div))
            
            figure_tags = soup.find_all('figure', class_='figure', limit=6)
            for i, fig in enumerate(figure_tags, 1):
                img = fig.find('img')
                if img:
                    img_url = img.get('src', '')
                    if img_url.startswith('/'):
                        img_url = urljoin(url, img_url)
                    figures.append({
                        'number': str(i),
                        'url': img_url,
                        'caption': f"Figure {i}"
                    })
        
        # RSC期刊
        elif journal == "Energy & Environmental Science":
            abs_div = (soup.find('div', {'id': 'abstract'}) or 
                      soup.find('p', class_='abstract'))
            if abs_div:
                abstract = clean_html(str(abs_div))
            
            figure_tags = soup.find_all('div', class_='img-tbl', limit=6)
            for i, fig in enumerate(figure_tags, 1):
                img = fig.find('img')
                if img:
                    img_url = img.get('src', '')
                    if img_url.startswith('/'):
                        img_url = urljoin(url, img_url)
                    figures.append({
                        'number': str(i),
                        'url': img_url,
                        'caption': f"Figure {i}"
                    })
        
        # 通用策略
        else:
            for tag in ['section', 'div']:
                abs_tag = soup.find(tag, string=re.compile('Abstract', re.I))
                if abs_tag:
                    abstract = clean_html(str(abs_tag))
                    break
            
            figure_tags = soup.find_all('figure', limit=6)
            for i, fig in enumerate(figure_tags, 1):
                img = fig.find('img')
                if img:
                    img_url = img.get('src', '')
                    if img_url.startswith('/'):
                        img_url = urljoin(url, img_url)
                    figures.append({
                        'number': str(i),
                        'url': img_url,
                        'caption': f"Figure {i}"
                    })
        
        # 清理abstract
        abstract = re.sub(r'^[Aa]bstract\s*[：:]?\s*', '', abstract).strip()
        
        return abstract, figures
        
    except Exception as e:
        print(f"      ⚠️ 爬取失败: {e}")
        return "", []

def fetch_papers():
    """第一步：只从RSS获取基本信息（不爬网页）"""
    all_papers = []
    cutoff_date = datetime.now() - timedelta(days=DAYS_BACK)
    
    print(f"正在抓取 {len(FEEDS)} 个期刊的RSS源...")
    print(f"筛选关键词: {', '.join(KEYWORDS)}")
    
    for journal, url in FEEDS.items():
        if not url:
            continue
            
        try:
            print(f"  📰 {journal}")
            
            response = requests.get(url, timeout=30, headers=HEADERS)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            
            for entry in feed.entries:
                try:
                    pub_date = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        pub_date = datetime(*entry.updated_parsed[:6])
                    
                    if pub_date and pub_date < cutoff_date:
                        continue
                    
                    authors = "Unknown"
                    if hasattr(entry, 'authors') and entry.authors:
                        author_list = [a.get('name', '') for a in entry.authors if a.get('name')]
                        if author_list:
                            authors = ", ".join(author_list[:3])
                            if len(entry.authors) > 3:
                                authors += " et al."
                    elif hasattr(entry, 'author'):
                        authors = entry.author
                    
                    # 只从RSS获取临时摘要（用于关键词筛选）
                    temp_summary = ""
                    if hasattr(entry, 'summary'):
                        temp_summary = clean_html(entry.summary)
                    elif hasattr(entry, 'description'):
                        temp_summary = clean_html(entry.description)
                    
                    title = clean_html(entry.get('title', 'No Title'))
                    link = entry.get('link', '')
                    doi = extract_doi(entry)
                    
                    paper = {
                        'title': title,
                        'link': link,
                        'doi': doi,
                        'summary': temp_summary,  # 临时摘要，用于筛选
                        'published': pub_date.strftime('%Y-%m-%d') if pub_date else datetime.now().strftime('%Y-%m-%d'),
                        'authors': authors,
                        'journal': journal,
                        'matched_keywords': [],
                        'research_story': '',
                        'figures': [],
                        'has_full_content': False  # 标记是否已爬取详细内容
                    }
                    
                    all_papers.append(paper)
                    
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"  ❌ {journal} 失败: {e}")
            continue
    
    all_papers.sort(key=lambda x: x['published'], reverse=True)
    print(f"\n✅ RSS获取完成：{len(all_papers)} 篇")
    return all_papers

def filter_by_keywords(papers):
    """第二步：关键词筛选"""
    if not papers:
        return []
    
    if not KEYWORDS:
        print("⚠️ 未设置关键词，返回所有文献")
        return papers
    
    print(f"\n🔍 关键词筛选（{', '.join(KEYWORDS)}）...")
    filtered = []
    
    for paper in papers:
        text_to_search = (paper['title'] + ' ' + paper['summary']).lower()
        matched = []
        for keyword in KEYWORDS:
            if keyword in text_to_search:
                matched.append(keyword)
        
        if matched:
            paper['matched_keywords'] = matched
            filtered.append(paper)
    
    print(f"🎯 筛选结果：{len(filtered)}/{len(papers)} 篇相关")
    return filtered

def fetch_article_details(papers):
    """第三步（新增）：只对筛选后的文章爬取网页详情（Abstract + Figures）"""
    if not papers:
        return []
    
    print(f"\n🌐 爬取筛选文章的详细内容（共{len(papers)}篇）...")
    
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] {paper['title'][:50]}...")
        
        if not paper.get('link'):
            continue
        
        # 爬取网页
        abstract, figures = fetch_article_content(paper['link'], paper['journal'])
        
        if abstract:
            paper['summary'] = abstract  # 用网页真实摘要替换RSS临时摘要
            print(f"      ✅ 获取到真实摘要")
        else:
            print(f"      ⚠️ 使用RSS摘要")
        
        if figures:
            paper['figures'] = figures
            print(f"      ✅ 获取到 {len(figures)} 张图片")
        else:
            print(f"      ⚠️ 未获取到图片")
        
        paper['has_full_content'] = True
        time.sleep(0.8)  # 避免请求过快被封
    
    print(f"\n✅ 详情爬取完成")
    return papers

def analyze_innovation(papers):
    """第四步：AI分析"""
    if not papers:
        return []
    
    if not ai_client:
        print("⚠️ 未配置AI API")
        for paper in papers:
            paper['research_story'] = "（未配置AI）"
        return papers
    
    print(f"\n🤖 AI深度解析（{len(papers)}篇）...")
    
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] {paper['title'][:50]}...")
        
        prompt = f"""请以领域专家视角撰写该论文的核心评述（200字左右）。

期刊：{paper['journal']}
标题：{paper['title']}
摘要：{paper['summary'][:1000]}

按以下逻辑：
1. **科学问题**：针对的具体技术瓶颈（1句）
2. **策略/方法**：核心解决思路与创新点（1-2句）
3. **机理/发现**：关键科学发现或作用机制（1-2句）
4. **性能/结果**：具体指标及与现有技术对比（1句）
5. **学术价值**：对领域的实质性推进（1句）

要求：专业术语、客观陈述、逻辑严密、无主观感叹、无空话。"""

        try:
            response = ai_client.chat.completions.create(
                model="gpt-3.5-turbo" if not BASE_URL else "deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是该领域资深研究者，撰写面向同行的学术评述，要求客观、精准、信息密度高。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.3
            )
            
            result = response.choices[0].message.content.strip()
            
            # 清理
            subjective_words = ["值得一提的是", "令人振奋的是", "值得注意的是", 
                "首次实现了", "开创性地", "极大地", "显著地", "为未来奠定了基础",
                "具有重要意义", "具有重要价值", "有望推动"]
            for word in subjective_words:
                result = result.replace(word, "")
            
            result = result.replace("。", "。\n")
            lines = [l.strip() for l in result.split('\n') if l.strip()]
            result = '\n\n'.join(lines)
            
            paper['research_story'] = result
            print(f"      ✅ 完成")
            
        except Exception as e:
            print(f"      ⚠️ 失败: {e}")
            paper['research_story'] = "（AI解析失败）"
    
    print(f"\n✅ AI解析完成")
    return papers

def generate_html(papers):
    today = datetime.now().strftime('%Y-%m-%d')
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>文献日报 - {today}</title>
    <style>
        :root {{
            --primary: #667eea;
            --secondary: #764ba2;
            --accent: #48bb78;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1100px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            min-height: 100vh;
            line-height: 1.6;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2d3748;
            text-align: center;
            margin-bottom: 10px;
            font-size: 32px;
        }}
        .subtitle {{
            text-align: center;
            color: #718096;
            margin-bottom: 30px;
            font-size: 16px;
        }}
        .stats {{
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 40px;
            text-align: center;
            font-size: 15px;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }}
        .paper {{
            border: 1px solid #e2e8f0;
            padding: 30px;
            margin: 30px 0;
            background: white;
            border-radius: 16px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            position: relative;
        }}
        .paper-title {{
            font-size: 22px;
            font-weight: 700;
            color: #2d3748;
            margin-bottom: 12px;
            line-height: 1.4;
        }}
        .paper-title a {{
            color: var(--primary);
            text-decoration: none;
        }}
        .paper-meta {{
            color: #4a5568;
            font-size: 14px;
            margin-bottom: 15px;
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
        }}
        .tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 10px 0;
        }}
        .journal-tag {{
            background: #e53e3e;
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
        }}
        .keyword-tag {{
            background: var(--accent);
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
        }}
        
        /* Abstract */
        .abstract-section {{
            background: #f8fafc;
            border-left: 4px solid #4299e1;
            padding: 20px;
            margin: 20px 0;
            border-radius: 0 8px 8px 0;
        }}
        .abstract-title {{
            font-weight: 700;
            color: #4299e1;
            font-size: 14px;
            margin-bottom: 10px;
        }}
        .abstract-content {{
            color: #4a5568;
            font-size: 15px;
            line-height: 1.8;
            text-align: justify;
        }}
        
        /* AI评述 */
        .research-story {{
            background: linear-gradient(135deg, #faf5ff 0%, #f0fff4 100%);
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            padding: 25px;
            margin-top: 25px;
        }}
        .story-header {{
            font-size: 16px;
            font-weight: 700;
            color: #2d3748;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e2e8f0;
        }}
        .story-content {{
            color: #2d3748;
            font-size: 15.5px;
            line-height: 1.9;
        }}
        .story-content p {{
            margin-bottom: 12px;
            text-align: justify;
        }}
        
        /* Figures折叠区域 */
        .figures-section {{
            margin-top: 25px;
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            overflow: hidden;
            background: #fff;
        }}
        .figures-toggle {{
            background: linear-gradient(135deg, #f6f8fb 0%, #e9edf5 100%);
            padding: 15px 20px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-weight: 600;
            color: #2d3748;
            font-size: 15px;
            transition: all 0.3s;
        }}
        .figures-toggle:hover {{
            background: linear-gradient(135deg, #e9edf5 0%, #dce3f0 100%);
        }}
        .figures-toggle::after {{
            content: "▼";
            transition: transform 0.3s;
            color: #718096;
        }}
        .figures-section.open .figures-toggle::after {{
            transform: rotate(180deg);
        }}
        .figures-container {{
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.5s ease;
            background: #fafbfc;
        }}
        .figures-section.open .figures-container {{
            max-height: 5000px;
        }}
        .figure-item {{
            padding: 25px;
            border-bottom: 1px solid #e2e8f0;
            text-align: center;
        }}
        .figure-number {{
            font-size: 16px;
            font-weight: 700;
            color: #2d3748;
            margin-bottom: 15px;
            text-align: left;
            padding-left: 10px;
            border-left: 4px solid var(--primary);
        }}
        .figure-image {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            margin-bottom: 12px;
            background: white;
            padding: 10px;
        }}
        .figure-caption {{
            font-size: 13px;
            color: #4a5568;
            text-align: left;
            line-height: 1.6;
            max-width: 90%;
            margin: 0 auto;
        }}
        
        /* 按钮 */
        .action-buttons {{
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin-top: 25px;
            padding-top: 20px;
            border-top: 2px solid #e2e8f0;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 10px 20px;
            border-radius: 8px;
            text-decoration: none;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s;
        }}
        .zotero-btn {{ background: linear-gradient(135deg, var(--primary), var(--secondary)); color: white; }}
        .pdf-btn {{ background: #e53e3e; color: white; }}
        .si-btn {{ background: #38a169; color: white; }}
        .source-btn {{ background: #718096; color: white; }}
        .btn:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
        
        mark {{
            background: #fef3c7;
            padding: 2px 4px;
            border-radius: 3px;
            font-weight: 600;
            color: #92400e;
        }}
        
        .ai-badge {{
            position: absolute;
            top: 20px;
            right: 20px;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
        }}
        
        .footer {{
            text-align: center;
            margin-top: 50px;
            padding-top: 30px;
            border-top: 2px solid #e2e8f0;
            color: #a0aec0;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📚 今日文献精选</h1>
        <div class="subtitle">先筛选 → 再爬详情 → AI解析</div>
        
        <div class="stats">
            <strong>筛选逻辑：</strong>RSS抓取 → 关键词筛选 → 爬取详情 → AI解析 | 
            <strong>关键词：</strong>{', '.join(KEYWORDS)} | 
            <strong>今日精选：</strong>{len(papers)}篇
        </div>
"""
    
    if not papers:
        html += '<div style="text-align:center;padding:60px;color:#718096;">今日暂无匹配文献</div>'
    else:
        for paper in papers:
            pdf_url, si_url = get_download_links(paper)
            zotero_link = f"https://www.zotero.org/save?url={quote(paper['link'])}&title={quote(paper['title'])}"
            
            # 高亮关键词
            display_title = paper['title']
            for kw in paper.get('matched_keywords', []):
                pattern = re.compile(re.escape(kw), re.IGNORECASE)
                display_title = pattern.sub(f'<mark>{kw}</mark>', display_title)
            
            # AI评述
            story_html = ""
            if paper.get('research_story') and "失败" not in paper['research_story']:
                story_text = paper['research_story']
                story_text = re.sub(r'(\d+\.?\d*%)', r'<mark>\1</mark>', story_text)
                paragraphs = story_text.split('\n\n')
                story_html = ''.join([f'<p>{p}</p>' for p in paragraphs])
            else:
                story_html = f'<p style="color:#718096;">{paper.get("research_story", "暂无解析")}</p>'
            
            # Figures
            figures_html = ""
            figures = paper.get('figures', [])
            if figures:
                figures_items = ""
                for fig in figures:
                    figures_items += f"""
                    <div class="figure-item">
                        <div class="figure-number">Figure {fig['number']}</div>
                        <img src="{fig['url']}" alt="Figure {fig['number']}" class="figure-image" loading="lazy" onerror="this.style.display='none'">
                        <div class="figure-caption">{fig.get('caption', '')}</div>
                    </div>
                    """
                figures_html = f"""
                <div class="figures-section" id="fig-{hash(paper['title']) % 10000}">
                    <div class="figures-toggle" onclick="this.parentElement.classList.toggle('open')">
                        <span>📊 查看原文图表</span>
                        <span style="color:#718096;font-size:13px;">{len(figures)}张图片 ▼</span>
                    </div>
                    <div class="figures-container">{figures_items}</div>
                </div>
                """
            
            buttons = (f'<a href="{zotero_link}" class="btn zotero-btn" target="_blank">➕ Zotero</a>' +
                      (f'<a href="{pdf_url}" class="btn pdf-btn" target="_blank">📄 PDF</a>' if pdf_url else '') +
                      (f'<a href="{si_url}" class="btn si-btn" target="_blank">📎 SI</a>' if si_url else '') +
                      f'<a href="{paper["link"]}" class="btn source-btn" target="_blank">🔗 原文</a>')
            
            html += f"""
        <div class="paper">
            <div class="ai-badge">AI深度解析</div>
            
            <div class="paper-title">
                <a href="{paper['link']}" target="_blank">{display_title}</a>
            </div>
            <div class="paper-meta">
                <span>👤 {paper['authors']}</span>
                <span>📅 {paper['published']}</span>
                <span>📰 {paper['journal']}</span>
            </div>
            <div class="tags">
                <span class="journal-tag">{paper['journal']}</span>
                {"".join([f'<span class="keyword-tag">{k}</span>' for k in paper.get('matched_keywords', [])])}
            </div>
            
            <div class="abstract-section">
                <div class="abstract-title">📝 原文摘要</div>
                <div class="abstract-content">{paper['summary']}</div>
            </div>
            
            <div class="research-story">
                <div class="story-header">🔬 专家评述</div>
                <div class="story-content">{story_html}</div>
            </div>
            
            {figures_html}
            
            <div class="action-buttons">{buttons}</div>
        </div>
"""
    
    html += f"""
        <div class="footer">
            <p>自动生成于 {today} | 先筛选后爬取 | {'DeepSeek' if BASE_URL else 'OpenAI'} AI解析</p>
        </div>
    </div>
</body>
</html>
"""
    
    os.makedirs('docs', exist_ok=True)
    with open('docs/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    with open('docs/papers.json', 'w', encoding='utf-8') as f:
        json.dump({
            'date': today,
            'keywords': KEYWORDS,
            'count': len(papers),
            'papers': papers
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 网页已生成：{len(papers)}篇文献")

if __name__ == '__main__':
    try:
        # 1. RSS抓取（快速）
        papers = fetch_papers()
        
        # 2. 关键词筛选
        filtered = filter_by_keywords(papers)
        
        # 3. 对筛选后的文章爬网页（耗时）
        detailed = fetch_article_details(filtered)
        
        # 4. AI分析
        analyzed = analyze_innovation(detailed)
        
        # 5. 生成网页
        generate_html(analyzed)
        print("\n🎉 全部完成！")
        
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

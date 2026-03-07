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

# 请求头，模拟浏览器
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
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
    """
    访问文章网页获取真实Abstract和Figures
    返回: (abstract_text, figures_list)
    figures_list: [{'number': '1', 'url': '...', 'caption': '...'}, ...]
    """
    try:
        print(f"      🌐 正在爬取网页: {url[:60]}...")
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        abstract = ""
        figures = []
        
        # 根据不同期刊解析HTML
        if journal in ["Nature", "Nature Communications", "Nature Energy", "Nature Synthesis"]:
            # Nature系列
            abs_div = soup.find('div', {'id': 'Abs1-content'}) or soup.find('div', class_='c-article-teaser__text')
            if abs_div:
                abstract = clean_html(str(abs_div))
            
            # 获取Figures - Nature通常在<div class="c-article-section__figure">
            figure_tags = soup.find_all('figure')
            for i, fig in enumerate(figure_tags[:6], 1):  # 限制前6个图避免太多
                img = fig.find('img')
                caption = fig.find('figcaption')
                if img and caption:
                    img_url = img.get('src', '')
                    if img_url.startswith('/'):
                        img_url = urljoin(url, img_url)
                    figures.append({
                        'number': str(i),
                        'url': img_url,
                        'caption': clean_html(str(caption))[:200] + "..."
                    })
        
        elif journal in ["Angewandte Chemie", "Advanced Materials", 
                        "Advanced Energy Materials", "Advanced Functional Materials"]:
            # Wiley期刊
            abs_section = soup.find('section', {'id': 'abstract'}) or soup.find('div', class_='article-section__abstract')
            if abs_section:
                abstract = clean_html(str(abs_section))
            
            # Figures - Wiley在<div class="figure">
            figure_divs = soup.find_all('div', class_='figure')
            for i, fig in enumerate(figure_divs[:6], 1):
                img = fig.find('img')
                caption = fig.find('div', class_='figure__caption')
                if img:
                    img_url = img.get('src', '')
                    if img_url.startswith('/'):
                        img_url = urljoin(url, img_url)
                    figures.append({
                        'number': str(i),
                        'url': img_url,
                        'caption': clean_html(str(caption))[:200] + "..." if caption else f"Figure {i}"
                    })
        
        elif journal == "Joule":
            # Cell Press
            abs_div = soup.find('div', class_='abstract') or soup.find('section', {'id': 'abstract'})
            if abs_div:
                abstract = clean_html(str(abs_div))
            
            # Figures
            figure_tags = soup.find_all('figure', class_='figure')
            for i, fig in enumerate(figure_tags[:6], 1):
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
        
        elif journal == "Energy & Environmental Science":
            # RSC期刊
            abs_div = soup.find('div', {'id': 'abstract'}) or soup.find('p', class_='abstract')
            if abs_div:
                abstract = clean_html(str(abs_div))
            
            # Figures
            figure_tags = soup.find_all('div', class_='img-tbl')
            for i, fig in enumerate(figure_tags[:6], 1):
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
        
        else:
            # 通用策略
            # Abstract: 找包含"Abstract"的div或section
            for tag in ['section', 'div', 'p']:
                abs_tag = soup.find(tag, string=re.compile('Abstract', re.I))
                if abs_tag:
                    abstract = clean_html(str(abs_tag))
                    break
            
            # Figures: 找所有figure标签
            figure_tags = soup.find_all('figure')[:6]
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
        
        # 清理abstract，去除"Abstract"字样
        abstract = re.sub(r'^[Aa]bstract\s*[：:]?\s*', '', abstract).strip()
        
        return abstract, figures
        
    except Exception as e:
        print(f"      ⚠️ 爬取网页失败: {e}")
        return "", []

def fetch_papers():
    all_papers = []
    cutoff_date = datetime.now() - timedelta(days=DAYS_BACK)
    
    print(f"正在抓取 {len(FEEDS)} 个期刊的RSS源...")
    print(f"筛选关键词: {', '.join(KEYWORDS)}")
    
    for journal, url in FEEDS.items():
        if not url:
            continue
            
        try:
            print(f"  📰 正在获取: {journal}")
            
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
                    
                    title = clean_html(entry.get('title', 'No Title'))
                    link = entry.get('link', '')
                    doi = extract_doi(entry)
                    
                    # 尝试从网页获取真实Abstract和Figures（如果失败则回退到RSS）
                    web_abstract = ""
                    figures = []
                    
                    if link and not link.endswith('.pdf'):
                        web_abstract, figures = fetch_article_content(link, journal)
                        time.sleep(0.5)  # 避免请求过快
                    
                    # 如果网页抓取失败，回退到RSS摘要
                    if not web_abstract:
                        summary = ""
                        if hasattr(entry, 'summary'):
                            summary = clean_html(entry.summary)
                        elif hasattr(entry, 'description'):
                            summary = clean_html(entry.description)
                        web_abstract = summary if summary else "（暂无摘要）"
                    
                    paper = {
                        'title': title,
                        'link': link,
                        'doi': doi,
                        'summary': web_abstract,  # 使用网页抓取的真实摘要
                        'published': pub_date.strftime('%Y-%m-%d') if pub_date else datetime.now().strftime('%Y-%m-%d'),
                        'authors': authors,
                        'journal': journal,
                        'matched_keywords': [],
                        'research_story': '',
                        'figures': figures  # 新增：存储图片列表
                    }
                    
                    all_papers.append(paper)
                    
                except Exception as e:
                    print(f"    ⚠️ 处理单篇文献出错: {e}")
                    continue
                    
        except Exception as e:
            print(f"  ❌ 获取 {journal} 失败: {e}")
            continue
    
    all_papers.sort(key=lambda x: x['published'], reverse=True)
    print(f"\n✅ 总共获取到 {len(all_papers)} 篇文献")
    return all_papers

def filter_by_keywords(papers):
    if not papers:
        return []
    
    if not KEYWORDS:
        print("⚠️ 未设置关键词，返回所有文献")
        return papers
    
    print(f"\n🔍 第一步：关键词匹配（{len(KEYWORDS)}个关键词）...")
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
    
    print(f"🎯 关键词筛选完成：{len(filtered)}/{len(papers)} 篇相关文献")
    return filtered

def analyze_innovation(papers):
    if not papers:
        return []
    
    if not ai_client:
        print("⚠️ 未配置AI API，跳过深度解析")
        for paper in papers:
            paper['research_story'] = "（未配置AI）"
        return papers
    
    print(f"\n🤖 第二步：AI深度解析（共{len(papers)}篇）...")
    
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] AI分析: {paper['title'][:50]}...")
        
        prompt = f"""请以领域专家视角，用严谨学术语言撰写该论文的核心评述（200-250字）。

期刊：{paper['journal']}
标题：{paper['title']}
摘要：{paper['summary'][:1200]}

写作要求：
1. **科学问题**：明确指出该工作针对的具体技术瓶颈或科学难题（1句话）
2. **策略/方法**：阐述核心解决思路，突出关键材料/方法/结构的创新性（1-2句话）
3. **机理/发现**：说明关键科学发现或作用机制，避免泛泛而谈（1-2句话）  
4. **性能/结果**：给出具体性能指标及与现有技术的对比基准（state-of-the-art）（1句话）
5. **学术价值**：点明对领域的实质性推进（理论贡献或技术突破）（1句话）

风格要求：
- 使用专业术语，避免科普化表达
- 客观陈述，不夸大，突出技术细节
- 逻辑严密：问题→策略→机理→结果→价值
- 禁止出现"值得一提的是"、"令人振奋的是"等主观感叹
- 禁止出现"为未来...奠定了基础"等空话"""

        try:
            response = ai_client.chat.completions.create(
                model="gpt-3.5-turbo" if not BASE_URL else "deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是该领域的资深研究者，撰写的是面向同行的学术评述，要求客观、精准、信息密度高。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.3
            )
            
            result = response.choices[0].message.content.strip()
            
            # 清理主观词
            subjective_words = ["值得一提的是", "令人振奋的是", "值得注意的是", "令人惊讶的是",
                "首次实现了", "开创性地", "极大地", "显著地", "为未来奠定了基础",
                "具有重要意义", "具有重要价值", "有望推动", "将改变"]
            for word in subjective_words:
                result = result.replace(word, "")
            
            result = result.replace("。", "。\n").replace(".\n", ".\n\n")
            lines = [l.strip() for l in result.split('\n') if l.strip()]
            result = '\n\n'.join(lines)
            
            paper['research_story'] = result
            print(f"      ✅ 解析完成")
            
        except Exception as e:
            print(f"      ⚠️ AI解析失败: {e}")
            paper['research_story'] = "（AI解析失败）"
    
    print(f"\n✅ AI深度解析完成")
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
            --bg: #f7fafc;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
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
            transition: all 0.3s ease;
            position: relative;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }}
        .paper:hover {{
            transform: translateY(-5px);
            box-shadow: 0 8px 30px rgba(0,0,0,0.12);
            border-color: var(--primary);
        }}
        .paper-header {{
            border-bottom: 2px solid #edf2f7;
            padding-bottom: 20px;
            margin-bottom: 20px;
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
        .paper-title a:hover {{
            text-decoration: underline;
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
            margin-top: 10px;
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
            font-weight: 500;
        }}
        
        /* Abstract部分 */
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
            display: flex;
            align-items: center;
            gap: 8px;
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
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .story-content {{
            color: #2d3748;
            font-size: 15.5px;
            line-height: 1.9;
            text-align: justify;
        }}
        .story-content p {{
            margin-bottom: 12px;
        }}
        
        /* Figures折叠区域 - 新增 */
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
            border-bottom: 2px solid transparent;
            transition: all 0.3s;
        }}
        .figures-toggle:hover {{
            background: linear-gradient(135deg, #e9edf5 0%, #dce3f0 100%);
        }}
        .figures-toggle::before {{
            content: "📊";
            margin-right: 8px;
            font-size: 18px;
        }}
        .figures-toggle::after {{
            content: "▼";
            transition: transform 0.3s;
            color: #718096;
        }}
        .figures-section.open .figures-toggle::after {{
            transform: rotate(180deg);
        }}
        .figures-toggle .count {{
            font-size: 13px;
            color: #718096;
            font-weight: 500;
            margin-left: auto;
            margin-right: 10px;
        }}
        .figures-container {{
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.5s ease-out;
            background: #fafbfc;
        }}
        .figures-section.open .figures-container {{
            max-height: 3000px; /* 足够大的高度 */
            transition: max-height 0.5s ease-in;
        }}
        .figure-item {{
            padding: 25px;
            border-bottom: 1px solid #e2e8f0;
            text-align: center;
        }}
        .figure-item:last-child {{
            border-bottom: none;
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
        .no-figures {{
            padding: 40px;
            text-align: center;
            color: #718096;
            font-style: italic;
        }}
        
        /* 操作按钮 */
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
            border: none;
            cursor: pointer;
        }}
        .zotero-btn {{
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
        }}
        .pdf-btn {{
            background: #e53e3e;
            color: white;
        }}
        .si-btn {{
            background: #38a169;
            color: white;
        }}
        .source-btn {{
            background: #718096;
            color: white;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}
        
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
        <div class="subtitle">智能筛选 · 深度解读 · 原文图表</div>
        
        <div class="stats">
            <strong>筛选模式：</strong>关键词匹配 + AI深度解析 + 原文Figure抓取 | 
            <strong>关键词：</strong>{', '.join(KEYWORDS)} | 
            <strong>精选文献：</strong>{len(papers)}篇
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
            if paper.get('research_story') and paper['research_story'] != "（AI解析失败）":
                story_text = paper['research_story']
                story_text = re.sub(r'(\d+\.?\d*%)', r'<mark>\1</mark>', story_text)
                paragraphs = story_text.split('\n\n')
                story_html = ''.join([f'<p>{p}</p>' for p in paragraphs])
            else:
                story_html = f'<p style="color:#718096;">{paper.get("research_story", "AI解析中...")}</p>'
            
            # Figures HTML（可折叠）
            figures_html = ""
            figures = paper.get('figures', [])
            if figures:
                figures_count = len(figures)
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
                <div class="figures-section" id="figures-{hash(paper['title']) % 10000}">
                    <div class="figures-toggle" onclick="toggleFigures(this)">
                        <span>📊 查看原文图表 (Figures)</span>
                        <span class="count">{figures_count}张图片</span>
                    </div>
                    <div class="figures-container">
                        {figures_items}
                    </div>
                </div>
                """
            else:
                figures_html = f"""
                <div class="figures-section">
                    <div class="figures-toggle" style="cursor: default; opacity: 0.6;">
                        <span>📊 原文图表</span>
                        <span class="count">未抓取到图片</span>
                    </div>
                </div>
                """
            
            # 按钮
            buttons = f'<a href="{zotero_link}" class="btn zotero-btn" target="_blank">➕ 添加到Zotero</a>'
            if pdf_url:
                buttons += f'<a href="{pdf_url}" class="btn pdf-btn" target="_blank">📄 下载PDF</a>'
            if si_url:
                buttons += f'<a href="{si_url}" class="btn si-btn" target="_blank">📎 查看SI</a>'
            buttons += f'<a href="{paper["link"]}" class="btn source-btn" target="_blank">🔗 原文链接</a>'
            
            html += f"""
        <div class="paper">
            <div class="ai-badge">AI深度解析</div>
            
            <div class="paper-header">
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
            </div>
            
            <div class="abstract-section">
                <div class="abstract-title">📝 原文摘要（Abstract）</div>
                <div class="abstract-content">{paper['summary']}</div>
            </div>
            
            <div class="research-story">
                <div class="story-header">
                    <span>🔬</span>
                    <span>专家评述</span>
                </div>
                <div class="story-content">
                    {story_html}
                </div>
            </div>
            
            {figures_html}
            
            <div class="action-buttons">
                {buttons}
            </div>
        </div>
"""
    
    html += f"""
        <div class="footer">
            <p>自动生成于 {today} | 关键词筛选 + {'DeepSeek' if BASE_URL else 'OpenAI'} AI解析 + 网页图表抓取</p>
            <p style="margin-top:10px;font-size:12px;">注意：图表抓取受期刊网站结构影响，部分图片可能无法显示</p>
        </div>
    </div>
    
    <script>
        function toggleFigures(element) {{
            const section = element.parentElement;
            section.classList.toggle('open');
        }}
    </script>
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
            count: len(papers),
            'papers': papers
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 网页已生成：docs/index.html（{len(papers)}篇文献）")

if __name__ == '__main__':
    try:
        papers = fetch_papers()
        filtered = filter_by_keywords(papers)
        analyzed = analyze_innovation(filtered)
        generate_html(analyzed)
        print("\n🎉 全部完成！")
    except Exception as e:
        print(f"\n❌ 程序运行失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

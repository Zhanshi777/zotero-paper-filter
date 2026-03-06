import feedparser
import os
import json
from datetime import datetime, timedelta
from urllib.parse import quote
import re
import html
import requests
import openai

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

# ==================== 核心函数 ====================

def clean_html(text):
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = html.unescape(clean)
    return clean.strip()

def extract_doi(entry):
    """从entry中提取DOI"""
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
    """生成PDF和SI下载/查看链接"""
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

def fetch_papers():
    """从所有RSS源获取最近文献"""
    all_papers = []
    cutoff_date = datetime.now() - timedelta(days=DAYS_BACK)
    
    print(f"正在抓取 {len(FEEDS)} 个期刊的RSS源...")
    print(f"筛选关键词: {', '.join(KEYWORDS)}")
    
    for journal, url in FEEDS.items():
        if not url:
            continue
            
        try:
            print(f"  📰 正在获取: {journal}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, timeout=30, headers=headers)
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
                    
                    # 改进的摘要提取
                    summary = ""
                    possible_fields = [
                        ('content', lambda x: x[0].value if isinstance(x, list) else x.value if hasattr(x, 'value') else str(x)),
                        ('summary', lambda x: str(x)),
                        ('description', lambda x: str(x)),
                    ]
                    
                    for field_name, extractor in possible_fields:
                        if hasattr(entry, field_name) and getattr(entry, field_name):
                            try:
                                raw_content = getattr(entry, field_name)
                                extracted = extractor(raw_content)
                                if extracted and len(extracted) > 50:
                                    summary = clean_html(extracted)
                                    break
                            except:
                                continue
                    
                    # 过滤期刊元数据
                    if summary:
                        metadata_patterns = [
                            r'Volume\s+\d+,\s*Issue\s+\d+',
                            r'©\s*\d{4}\s+[\w\s]+Ltd',
                            r'https://doi\.org/',
                        ]
                        is_metadata = False
                        for pattern in metadata_patterns:
                            if re.search(pattern, summary, re.IGNORECASE) and len(summary) < 500:
                                is_metadata = True
                                break
                        if is_metadata:
                            summary = ""
                    
                    if not summary and hasattr(entry, 'dc_description'):
                        summary = clean_html(entry.dc_description)
                    
                    title = clean_html(entry.get('title', 'No Title'))
                    doi = extract_doi(entry)
                    
                    paper = {
                        'title': title,
                        'link': entry.get('link', ''),
                        'doi': doi,
                        'summary': summary if summary else "（该期刊RSS未提供文章摘要，请点击查看原文）",
                        'published': pub_date.strftime('%Y-%m-%d') if pub_date else datetime.now().strftime('%Y-%m-%d'),
                        'authors': authors,
                        'journal': journal,
                        'matched_keywords': [],
                        'research_story': ''  # AI连贯叙述
                    }
                    
                    all_papers.append(paper)
                    
                except Exception as e:
                    continue
                    
        except Exception as e:
            print(f"  ❌ 获取 {journal} 失败: {e}")
            continue
    
    all_papers.sort(key=lambda x: x['published'], reverse=True)
    print(f"\n✅ 总共获取到 {len(all_papers)} 篇文献")
    return all_papers

def filter_by_keywords(papers):
    """关键词快速筛选"""
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
    """AI深度解析：生成连贯的研究故事"""
    if not papers:
        return []
    
    if not ai_client:
        print("⚠️ 未配置AI API，跳过深度解析")
        for paper in papers:
            paper['research_story'] = "（未配置AI，无法生成深度解析）"
        return papers
    
    print(f"\n🤖 第二步：AI深度解析（共{len(papers)}篇）...")
    print(f"   使用API: {'DeepSeek' if BASE_URL else 'OpenAI'}")
    
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] AI分析: {paper['title'][:50]}...")
        
        prompt = f"""请用2-3段连贯的文字（总共250-350字），像撰写科学新闻一样讲述这篇论文的研究故事：

期刊：{paper['journal']}
标题：{paper['title']}
摘要：{paper['summary'][:1000]}

要求按以下逻辑路线叙述：
1. 开篇点明研究背景和要解决的关键科学问题（领域痛点）
2. 阐述作者采用的核心策略/方法（"鉴于此，作者通过..."）
3. 说明关键发现或作用机制（"研究表明/计算发现..."）
4. 最后点明取得的具体成果和性能数据（带具体数值）

要求：
- 语言流畅，逻辑清晰，使用连接词（鉴于此、结果表明、最终等）
- 不要分点，不要小标题，像讲故事一样自然过渡
- 必须包含具体性能数据（效率、稳定性数值等）
- 突出文章的逻辑链条：问题→策略→机制→成果"""

        try:
            response = ai_client.chat.completions.create(
                model="gpt-3.5-turbo" if not BASE_URL else "deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是资深的材料科学领域科学写作专家，擅长用流畅的中文撰写学术新闻-style的研究解读。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=600,
                temperature=0.6
            )
            
            result = response.choices[0].message.content.strip()
            
            # 清理格式：确保段落间有适当空行
            paragraphs = [p.strip() for p in result.split('\n\n') if p.strip()]
            if len(paragraphs) == 1:
                # 如果只有一段，尝试按句号分段
                sentences = re.split(r'([。！])', paragraphs[0])
                new_paragraphs = []
                current_para = ""
                for j in range(0, len(sentences)-1, 2):
                    current_para += sentences[j] + (sentences[j+1] if j+1 < len(sentences) else "")
                    if len(current_para) > 80:  # 每段约80字后换段
                        new_paragraphs.append(current_para)
                        current_para = ""
                if current_para:
                    new_paragraphs.append(current_para)
                paragraphs = new_paragraphs if new_paragraphs else paragraphs
            
            paper['research_story'] = '\n\n'.join(paragraphs)
            print(f"      ✅ 解析完成（{len(result)}字）")
            
        except Exception as e:
            print(f"      ⚠️ AI解析失败: {e}")
            paper['research_story'] = "（AI解析失败，请查看原文获取详细信息）"
    
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
        .stats strong {{
            color: #ffd700;
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
        
        /* 原文摘要 */
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
        
        /* AI连贯叙述 */
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
            margin-bottom: 15px;
            text-indent: 2em;
        }}
        /* 高亮关键数据 */
        .story-content .highlight-data {{
            background: linear-gradient(120deg, #fef3c7 0%, #fde68a 100%);
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 600;
            color: #92400e;
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
        }}
        .zotero-btn {{
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }}
        .zotero-btn:hover {{
            transform: translateY(-2px);
        }}
        .pdf-btn {{
            background: #e53e3e;
            color: white;
        }}
        .pdf-btn:hover {{
            background: #c53030;
            transform: translateY(-2px);
        }}
        .si-btn {{
            background: #38a169;
            color: white;
        }}
        .si-btn:hover {{
            background: #2f855a;
            transform: translateY(-2px);
        }}
        .source-btn {{
            background: #718096;
            color: white;
        }}
        .source-btn:hover {{
            background: #4a5568;
            transform: translateY(-2px);
        }}
        
        .oa-note {{
            font-size: 12px;
            color: #718096;
            margin-top: 10px;
            font-style: italic;
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
        <div class="subtitle">智能筛选 · 深度解读 · 一键下载</div>
        
        <div class="stats">
            <strong>筛选模式：</strong>关键词匹配 + AI深度解析 | 
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
            
            # 处理AI叙述：高亮关键数据
            story_html = ""
            if paper.get('research_story') and paper['research_story'] != "（AI解析失败，请查看原文获取详细信息）":
                story_text = paper['research_story']
                # 高亮百分比
                story_text = re.sub(r'(\d+\.?\d*%)', r'<span class="highlight-data">\1</span>', story_text)
                # 高亮时间
                story_text = re.sub(r'(\d+\s*(小时|h|天|年))', r'<span class="highlight-data">\1</span>', story_text)
                # 转为HTML段落
                paragraphs = story_text.split('\n\n')
                story_html = ''.join([f'<p>{p}</p>' for p in paragraphs])
            else:
                story_html = f'<p style="color:#718096;">{paper.get("research_story", "AI解析中...")}</p>'
            
            # 构建按钮
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
                    <span>研究深度解读</span>
                </div>
                <div class="story-content">
                    {story_html}
                </div>
            </div>
            
            <div class="action-buttons">
                {buttons}
            </div>
            <div class="oa-note">💡 提示：PDF按钮对于Open Access文献可直接下载，订阅制文献将跳转到期刊网站</div>
        </div>
"""
    
    html += f"""
        <div class="footer">
            <p>自动生成于 {today} | 关键词筛选 + {'DeepSeek' if BASE_URL else 'OpenAI'} AI深度解析</p>
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

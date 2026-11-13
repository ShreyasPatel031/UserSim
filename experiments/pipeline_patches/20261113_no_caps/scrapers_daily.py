import os,json,time,urllib.request,urllib.parse,datetime,re,xml.etree.ElementTree as ET
# Bundle 11 (no-caps rule, AGENTS.md Nov 13): every query is paged to the source's end and text is kept in full.
# Was: posts first:20 (N newest only), comments first:10, HN hits[:20], GitHub per_page 5, reddit content[:4000],
# Apple search limit 3 + review page 1. Source-side limits that remain are noted at each call (SOURCE LIMIT).
UA=os.environ.get("SCR_UA","UserSim-research/1.0 (read-only)")
D=datetime.date.today().isoformat(); OUT=os.environ.get("OUT","/tmp/scr_out"); NOW=datetime.datetime.utcnow().isoformat()+"Z"
def get(u,h=None,data=None):
    time.sleep(6.5); r=urllib.request.Request(u,data=data,headers={"User-Agent":UA,**(h or {})}); return urllib.request.urlopen(r,timeout=30).read()
def w(src,rows):
    os.makedirs(f"{OUT}/{src}",exist_ok=True)
    with open(f"{OUT}/{src}/{D}.jsonl","a") as f:
        for r in rows: f.write(json.dumps(r)+"\n")
    print(src,len(rows))
tok=[l.split("=",1)[1].strip() for l in open(os.environ.get("PHTOK","/workspace/secrets/ph_dev_token.env")) if l.startswith("PH_TOKEN")][0]
H={"Authorization":"Bearer "+tok,"Content-Type":"application/json"}
def gql(q,v):
    while True:
        b=json.loads(get("https://api.producthunt.com/v2/api/graphql",H,json.dumps({"query":q,"variables":v}).encode()))
        e=b.get("errors") or []
        if e and e[0].get("error")=="rate_limit_reached": time.sleep(int(e[0]["details"]["reset_in"])+5); continue
        if "data" not in b or not b["data"]: print("PH ERR",str(b)[:300]); raise SystemExit(1)
        return b["data"]
# every post created in the last 24 h (was: the N newest), paged by cursor until hasNextPage is false
since=(datetime.datetime.utcnow()-datetime.timedelta(hours=int(os.environ.get("HOURS","24")))).isoformat()+"Z"
QP='query($c:String,$a:DateTime){posts(first:20,after:$c,order:NEWEST,postedAfter:$a){pageInfo{hasNextPage endCursor} edges{node{id name slug tagline url votesCount commentsCount reviewsRating createdAt comments(first:20){pageInfo{hasNextPage endCursor} edges{node{body votesCount createdAt}}}}}}}'
QC='query($id:ID!,$c:String){post(id:$id){comments(first:20,after:$c){pageInfo{hasNextPage endCursor} edges{node{body votesCount createdAt}}}}}'
posts,cur=[],None
while True:
    p=gql(QP,{"c":cur,"a":since})["posts"]; posts+=[e["node"] for e in p["edges"]]
    if not p["pageInfo"]["hasNextPage"]: break
    cur=p["pageInfo"]["endCursor"]
for p in posts:   # every comment of every post (was first:10)
    cm=p.get("comments") or {}; edges=list(cm.get("edges") or []); pi=cm.get("pageInfo") or {}
    while pi.get("hasNextPage"):
        c=gql(QC,{"id":p["id"],"c":pi["endCursor"]})["post"]["comments"]; edges+=c["edges"]; pi=c["pageInfo"]
    p["comments"]={"edges":edges}
w("producthunt_api",[{**p,"fetched_at":NOW} for p in posts])
hn,rd,gh,ap=[],[],[],[]
for p in posts:
    n=p["name"]
    try:   # every hit, every page (was hits[:20]); SOURCE LIMIT: Algolia serves at most 1,000 hits per query
        pg=0
        while True:
            r=json.loads(get("https://hn.algolia.com/api/v1/search?"+urllib.parse.urlencode({"query":n,"numericFilters":"created_at_i>%d"%(time.time()-30*86400),"hitsPerPage":1000,"page":pg})))
            for h in r["hits"]:
                hn.append({"launch":p["slug"],"id":h["objectID"],"type":h.get("_tags",[""])[0],"title":h.get("title"),"text":h.get("comment_text") or h.get("story_text"),"points":h.get("points"),"created_at":h["created_at"],"fetched_at":NOW})
            pg+=1
            if pg>=r.get("nbPages",0): break
    except Exception as e: print("hn",n,e)
    try:   # full content (was [:4000]); every page via after= (was the first 25); SOURCE LIMIT: reddit search returns at most ~250 per query
        after=None
        for _ in range(20):
            time.sleep(20); qs={"q":"\"%s\""%n,"sort":"new","t":"month","limit":100}
            if after: qs["after"]=after
            root=ET.fromstring(get("https://www.reddit.com/search.rss?"+urllib.parse.urlencode(qs)))
            ents=root.findall("{http://www.w3.org/2005/Atom}entry")
            for en in ents:
                g=lambda t:(en.find("{http://www.w3.org/2005/Atom}"+t))
                rd.append({"launch":p["slug"],"id":(g("id").text if g("id") is not None else None),"title":g("title").text,"link":g("link").get("href"),"updated":g("updated").text,"content":re.sub("<[^>]+>"," ",(g("content").text or "")),"fetched_at":NOW})
            if len(ents)<100: break
            after=ents[-1].find("{http://www.w3.org/2005/Atom}id").text
    except Exception as e: print("reddit",n,e)
    try:   # every repo (was per_page 5); SOURCE LIMIT: GitHub search serves at most 1,000 results per query
        page=1
        while True:
            r=json.loads(get("https://api.github.com/search/repositories?"+urllib.parse.urlencode({"q":n+" in:name,description","per_page":100,"page":page})))
            for x in r["items"]:
                gh.append({"launch":p["slug"],"repo":x["full_name"],"stars":x["stargazers_count"],"forks":x["forks_count"],"open_issues":x["open_issues_count"],"created_at":x["created_at"],"fetched_at":NOW})
            if len(r["items"])<100 or page*100>=min(r.get("total_count",0),1000): break
            page+=1
    except Exception as e: print("gh",n,e)
    try:   # every matching app (was limit 3) and every review page; SOURCE LIMIT: Apple's review feed serves 10 pages x 50
        for r in json.loads(get("https://itunes.apple.com/search?"+urllib.parse.urlencode({"term":n,"entity":"software","limit":200})))["results"]:
            if n.lower() not in r["trackName"].lower(): continue
            reviews=[]
            for pg in range(1,11):
                rv=json.loads(get(f"https://itunes.apple.com/us/rss/customerreviews/page={pg}/id={r['trackId']}/sortby=mostrecent/json")).get("feed",{}).get("entry",[])
                got=[{"title":x["title"]["label"],"body":x["content"]["label"],"rating":x["im:rating"]["label"]} for x in rv if isinstance(x,dict) and "im:rating" in x]
                reviews+=got
                if not got: break
            ap.append({"launch":p["slug"],"app_id":r["trackId"],"app":r["trackName"],"rating":r.get("averageUserRating"),"rating_count":r.get("userRatingCount"),"reviews":reviews,"fetched_at":NOW})
    except Exception as e: print("apple",n,e)
w("hn_mentions",hn); w("reddit_mentions",rd); w("github_repos",gh); w("appstore_reviews",ap)

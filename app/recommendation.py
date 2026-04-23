from typing import List, Dict, Tuple
from sqlalchemy.orm import Session
from app.models import Job, Candidate, User


class RecommendationEngine:
    """简单关键词匹配推荐引擎 - 基于关键词重合度"""

    def __init__(self):
        pass

    def _extract_keywords(self, text: str) -> set:
        """提取关键词（简单分词）"""
        if not text:
            return set()

        # 转小写并分割
        text = text.lower()
        # 按逗号、空格、顿号等分割
        keywords = set()
        for separator in [',', '，', ' ', '、', ';', '；', '\n', '\t']:
            text = text.replace(separator, '|')

        for word in text.split('|'):
            word = word.strip()
            if word and len(word) > 0:
                keywords.add(word)

        return keywords

    def _get_candidate_keywords(self, candidate: Candidate) -> set:
        """获取求职者的关键词"""
        keywords = set()

        if candidate.skills:
            keywords.update(self._extract_keywords(candidate.skills))

        if candidate.target_job:
            keywords.update(self._extract_keywords(candidate.target_job))

        return keywords

    def _get_job_keywords(self, job: Job) -> set:
        """获取岗位的关键词"""
        keywords = set()

        if job.title:
            keywords.update(self._extract_keywords(job.title))

        if job.required_skills:
            keywords.update(self._extract_keywords(job.required_skills))

        return keywords

    def _calculate_keyword_match(
            self,
            keywords1: set,
            keywords2: set) -> float:
        """计算关键词匹配度"""
        if not keywords1 or not keywords2:
            return 0.0

        intersection = keywords1.intersection(keywords2)
        union = keywords1.union(keywords2)

        if len(union) == 0:
            return 0.0

        similarity = len(intersection) / len(union)
        match_boost = len(intersection) * 0.1
        final_score = min(similarity + match_boost, 1.0)

        return final_score

    def _parse_salary(self, salary_str: str) -> Tuple[float, float]:
        """解析薪资字符串，返回(最低薪资, 最高薪资)，单位统一为k"""
        if not salary_str:
            return (0.0, float('inf'))

        salary_str = salary_str.lower().replace(',', '').replace('，', '')
        salary_str = salary_str.replace('k', '').replace('K', '')
        salary_str = salary_str.replace('k/月', '').replace('k/月', '')
        salary_str = salary_str.replace('元/月', '').replace('元', '')

        numbers = []
        for part in salary_str.split('-'):
            part = part.strip()
            if part.isdigit():
                num = float(part)
                if num > 1000:
                    num = num / 1000
                numbers.append(num)

        if len(numbers) >= 2:
            return (min(numbers), max(numbers))
        elif len(numbers) == 1:
            return (numbers[0], numbers[0])
        else:
            return (0.0, float('inf'))

    def _calculate_salary_match(
            self,
            candidate_salary: str,
            job_salary: str) -> float:
        """计算薪资匹配度"""
        if not candidate_salary or not job_salary:
            return 0.5

        cand_min, cand_max = self._parse_salary(candidate_salary)
        job_min, job_max = self._parse_salary(job_salary)

        if job_min == 0 and job_max == float('inf'):
            return 0.5

        if cand_min <= job_min <= cand_max or cand_min <= job_max <= cand_max:
            return 1.0

        if job_max < cand_min:
            gap_ratio = (cand_min - job_max) / cand_min
            return max(0.0, 1.0 - gap_ratio * 0.5)

        if job_min > cand_max:
            return 1.0

        return 0.5

    def recommend_jobs_for_candidate(
        self,
        candidate: Candidate,
        jobs: List[Job],
        top_n: int = 5
    ) -> List[Tuple[Job, float]]:
        """为求职者推荐岗位 - 基于关键词匹配和薪资匹配"""
        if not jobs:
            return []

        candidate_keywords = self._get_candidate_keywords(candidate)
        if not candidate_keywords:
            return []

        job_scores = []
        for job in jobs:
            job_keywords = self._get_job_keywords(job)
            keyword_score = self._calculate_keyword_match(
                candidate_keywords, job_keywords)
            if keyword_score > 0:
                salary_score = self._calculate_salary_match(
                    candidate.expected_salary, job.salary_range)
                final_score = keyword_score * 0.8 + salary_score * 0.2
                job_scores.append((job, final_score))

        job_scores.sort(key=lambda x: x[1], reverse=True)

        return job_scores[:top_n]

    def recommend_candidates_for_job(
        self,
        job: Job,
        candidates: List[Candidate],
        top_n: int = 5
    ) -> List[Tuple[Candidate, float]]:
        """为岗位推荐求职者 - 基于关键词匹配和薪资匹配"""
        if not candidates:
            return []

        job_keywords = self._get_job_keywords(job)
        if not job_keywords:
            return []

        candidate_scores = []
        for candidate in candidates:
            candidate_keywords = self._get_candidate_keywords(candidate)
            keyword_score = self._calculate_keyword_match(
                job_keywords, candidate_keywords)
            if keyword_score > 0:
                salary_score = self._calculate_salary_match(
                    candidate.expected_salary, job.salary_range)
                final_score = keyword_score * 0.8 + salary_score * 0.2
                candidate_scores.append((candidate, final_score))

        candidate_scores.sort(key=lambda x: x[1], reverse=True)

        return candidate_scores[:top_n]

    def calculate_match_percentage(self, similarity_score: float) -> int:
        """将相似度分数转换为百分比"""
        return int(similarity_score * 100)


# 全局推荐引擎实例
recommendation_engine = RecommendationEngine()


def get_job_recommendations_for_user(
        db: Session,
        user_id: int,
        top_n: int = 5) -> List[Dict]:
    """获取用户的岗位推荐"""
    candidate = db.query(Candidate).filter(
        Candidate.user_id == user_id).first()
    if not candidate:
        return []

    # 获取所有活跃岗位
    active_jobs = db.query(Job).filter(Job.is_active).all()

    # 获取推荐
    recommendations = recommendation_engine.recommend_jobs_for_candidate(
        candidate, active_jobs, top_n)

    result = []
    for job, similarity in recommendations:
        result.append({
            "job": job,
            "similarity": similarity,
            "match_percentage": recommendation_engine.calculate_match_percentage(similarity)
        })

    return result


def get_candidate_recommendations_for_job(
        db: Session,
        job_id: int,
        top_n: int = 5) -> List[Dict]:
    """获取岗位的候选人推荐（只显示求职中的候选人）"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return []

    # 获取所有"求职中"的求职者
    candidates = db.query(Candidate).join(User).filter(
        User.role == "candidate",
        Candidate.job_status == "求职中"
    ).all()

    # 获取推荐
    recommendations = recommendation_engine.recommend_candidates_for_job(
        job, candidates, top_n)

    result = []
    for candidate, similarity in recommendations:
        result.append({
            "candidate": candidate,
            "similarity": similarity,
            "match_percentage": recommendation_engine.calculate_match_percentage(similarity)
        })

    return result

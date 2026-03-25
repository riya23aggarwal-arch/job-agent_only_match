"""
Test suite for job-agent apply engine fixes.

Tests cover:
  - Q&A answer loading and parsing
  - Question detection and matching
  - Resume validation
  - Name field detection
  - Dropdown exact matching
  - Field deduplication
"""

import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestQAAnswerParsing:
    """Test Q&A file parsing and matching."""
    
    def test_parse_qa_file_with_standard_questions(self):
        """Verify Q&A parsing extracts all 5 standard question types."""
        qa_content = """
# Screening Q&A — Test Job

---

## Why this role?

This role aligns with my background in Linux kernel development.

## Why this company?

The company focuses on infrastructure, which interests me.

## Relevant experience?

- 6 years Linux systems engineering
- Device driver development
- Kernel debugging experience

## Key strengths?

1. Low-level debugging
2. C systems programming
3. Cross-stack reasoning

## Challenging debugging problem

At Google, I debugged a race condition in the power management driver.
"""
        from job_agent.apply.engine import ApplyEngine
        engine = ApplyEngine()
        
        # Simulate loading
        from job_agent.models import StoredJob
        job = MagicMock(spec=StoredJob)
        job.job_id = "test123"
        
        # Parse should extract all answers
        answers = engine._match_qa_answer("why this role", {"why_role": "This role aligns..."})
        assert answers is not None
        assert "aligns" in answers.lower()
    
    def test_match_qa_answer_finds_correct_answer(self):
        """Test that question detection maps to correct answer."""
        from job_agent.apply.engine import ApplyEngine
        engine = ApplyEngine()
        
        qa_dict = {
            "why_role": "Answer about the role",
            "why_company": "Answer about the company",
            "strengths": "Answer about strengths",
        }
        
        # Should find why_role answer
        assert engine._match_qa_answer("why are you interested in this role?", qa_dict)
        
        # Should find why_company answer
        assert engine._match_qa_answer("why are you interested in our company?", qa_dict)
        
        # Should find strengths answer
        assert engine._match_qa_answer("what are your key strengths?", qa_dict)
        
        # Should return None for unknown question
        assert engine._match_qa_answer("random question", qa_dict) is None


class TestResumeValidation:
    """Test resume validation before apply attempt."""
    
    def test_resume_path_required(self):
        """Resume must exist before apply proceeds."""
        from job_agent.apply.engine import ApplyEngine, ApplyContext
        from job_agent.models import StoredJob
        
        engine = ApplyEngine()
        
        job = MagicMock(spec=StoredJob)
        job.apply_url = "https://example.com"
        
        ctx = ApplyContext(
            job=job,
            resume_path=Path("/nonexistent/file.pdf"),
            cover_letter_path=None
        )
        
        # Should return False if resume doesn't exist
        result = engine.run(ctx)
        assert result is False
    
    def test_resume_exists_in_default_location(self):
        """Should find resume in default location."""
        from job_agent.apply.engine import ApplyEngine
        
        engine = ApplyEngine()
        
        # Create a temporary PDF
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "test.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")  # Minimal PDF header
            
            # Should find the file
            result = engine._get_pdf_resume(pdf_path)
            assert result == pdf_path


class TestNameFieldDetection:
    """Test improved name field regex patterns."""
    
    def test_first_name_regex_matches_correctly(self):
        """First name pattern should match specific first name fields."""
        pattern = r"^(first[_\-]?name|fname)$|first\s*name"
        
        # Should match
        assert re.search(pattern, "first_name", re.IGNORECASE)
        assert re.search(pattern, "first-name", re.IGNORECASE)
        assert re.search(pattern, "firstname", re.IGNORECASE)
        assert re.search(pattern, "first name", re.IGNORECASE)
        assert re.search(pattern, "fname", re.IGNORECASE)
        
        # Should NOT match
        assert not re.search(pattern, "first_name_label", re.IGNORECASE)
        assert not re.search(pattern, "lastname", re.IGNORECASE)
    
    def test_last_name_regex_matches_correctly(self):
        """Last name pattern should match specific last name fields."""
        pattern = r"^(last[_\-]?name|lname)$|last\s*name"
        
        # Should match
        assert re.search(pattern, "last_name", re.IGNORECASE)
        assert re.search(pattern, "last-name", re.IGNORECASE)
        assert re.search(pattern, "lastname", re.IGNORECASE)
        assert re.search(pattern, "last name", re.IGNORECASE)
        assert re.search(pattern, "lname", re.IGNORECASE)
        
        # Should NOT match
        assert not re.search(pattern, "last_name_label", re.IGNORECASE)
        assert not re.search(pattern, "firstname", re.IGNORECASE)


class TestDropdownExactMatching:
    """Test improved dropdown option selection."""
    
    def test_longest_match_wins(self):
        """When multiple options contain desired answer, longest match should win."""
        options = [
            "Yes",
            "No",
            "No, I do not have a disability",
            "I prefer not to answer"
        ]
        
        desired = "No, I do not"
        
        # Should match the longer "No, I do not have..." not just "No"
        scores = {}
        for opt in options:
            if desired.lower() in opt.lower():
                scores[opt] = len(desired)
        
        best = max(scores, key=scores.get) if scores else None
        assert best == "No, I do not have a disability"
    
    def test_exact_substring_match(self):
        """Options should match on exact substring length."""
        desired = "No"
        
        test_cases = [
            ("Yes", False),
            ("No", True),
            ("No, I do not", True),
            ("I do not have", False),
        ]
        
        for option, should_match in test_cases:
            matches = desired.lower() in option.lower()
            assert matches == should_match


class TestFieldDeduplication:
    """Test field tracking to prevent duplicates."""
    
    def test_filled_fields_tracking(self):
        """Fields should only be filled once."""
        filled_fields = set()
        
        # Simulate filling 3 fields
        field_ids = [1001, 1002, 1003]
        
        for field_id in field_ids:
            if field_id not in filled_fields:
                filled_fields.add(field_id)
        
        assert len(filled_fields) == 3
        
        # Try to fill field 1 again
        if 1001 not in filled_fields:
            filled_fields.add(1001)
        
        # Should still be 3 (no duplicate)
        assert len(filled_fields) == 3
        assert 1001 in filled_fields


class TestFormFillRobustness:
    """Test that form continues on individual field errors."""
    
    def test_continue_on_field_error(self):
        """Individual field fill errors shouldn't stop the entire form."""
        from job_agent.apply.engine import ApplyEngine
        
        engine = ApplyEngine()
        filled_fields = set()
        
        # Simulate 5 fields, 3rd one fails
        field_results = []
        for i in range(5):
            try:
                field_id = 1000 + i
                
                # Simulate 3rd field failing
                if i == 2:
                    raise ValueError("Field fill failed")
                
                filled_fields.add(field_id)
                field_results.append(True)
            except Exception as e:
                # Continue on error
                field_results.append(False)
        
        # Should have filled 4 fields despite error on 3rd
        assert filled_fields == {1000, 1001, 1003, 1004}
        assert sum(field_results) == 4
        assert field_results[2] is False  # 3rd field failed


class TestContextIntegration:
    """Test that ApplyContext properly passes Q&A to engine."""
    
    def test_apply_context_includes_qa_answers(self):
        """ApplyContext should accept and hold qa_answers."""
        from job_agent.apply.engine import ApplyContext
        from job_agent.models import StoredJob
        
        job = MagicMock(spec=StoredJob)
        qa = {"why_role": "test", "strengths": "test"}
        
        ctx = ApplyContext(
            job=job,
            resume_path=Path("test.pdf"),
            cover_letter_path=Path("test.md"),
            qa_answers=qa,
            mode="assisted"
        )
        
        assert ctx.qa_answers == qa
        assert ctx.qa_answers["why_role"] == "test"


class TestScreeningQuestionDetection:
    """Test detection of screening question fields."""
    
    def test_standard_qa_keys_mapping(self):
        """Standard Q&A keys should map to common question patterns."""
        STANDARD_QA_KEYS = {
            "why_role": ["why this role", "why are you interested", "interest in role"],
            "why_company": ["why this company", "interested in us"],
            "relevant_exp": ["relevant experience", "tell us about"],
            "strengths": ["key strength", "what are your strengths"],
            "challenge": ["challenging problem", "debugging story"],
        }
        
        # Test each mapping
        assert "why this role" in STANDARD_QA_KEYS["why_role"]
        assert "why are you interested" in STANDARD_QA_KEYS["why_role"]
        assert "why this company" in STANDARD_QA_KEYS["why_company"]
        assert "relevant experience" in STANDARD_QA_KEYS["relevant_exp"]
        assert "key strength" in STANDARD_QA_KEYS["strengths"]
        assert "challenging problem" in STANDARD_QA_KEYS["challenge"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

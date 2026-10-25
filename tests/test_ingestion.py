import datetime as dt
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("updater", ROOT / "scripts" / "update_papers.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CONFIG = json.loads((ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
TOPICS = CONFIG["topics"]
VENUES = CONFIG["monitored_venues"]


def paper(title, abstract, keywords=None):
    return {"title": title, "abstract": abstract, "keywords": keywords or []}


class IngestionTests(unittest.TestCase):
    def test_normalize_doi_strips_prefix_and_lowercases(self):
        self.assertEqual(m.normalize_doi("https://doi.org/10.1145/ABC"), "10.1145/abc")

    def test_term_present_respects_boundaries_and_hyphens(self):
        text = m.searchable_text("We studied Human-AI collaboration in classrooms.")
        self.assertTrue(m.term_present("human-ai collaboration", text))
        self.assertFalse(m.term_present("ai", m.searchable_text("a survey of airline safety")))

    def test_topic_query_joins_groups_with_and(self):
        query = m.topic_query(TOPICS[0])
        self.assertIn("AND", query)
        self.assertIn("human-ai collaboration", query)
        self.assertIn("education", query)

    def test_reconstruct_abstract_from_inverted_index(self):
        inverted = {"The": [0], "study": [1], "used": [2], "AI": [3]}
        self.assertEqual(m.reconstruct_abstract(inverted), "The study used AI")
        self.assertIsNone(m.reconstruct_abstract(None))

    def test_education_requires_classroom_focus(self):
        result = m.classify(paper(
            "ChatGPT in the classroom",
            "Teachers used a large language model to support student learning."
        ), TOPICS)
        self.assertIn("human-ai-education", result["topics"])

    def test_machine_learning_is_not_education(self):
        result = m.classify(paper(
            "A machine learning model for EEG decoding",
            "We train a deep learning model to classify brain signals."
        ), TOPICS)
        self.assertNotIn("human-ai-education", result["topics"])

    def test_bci_psychology_viewpoint(self):
        result = m.classify(paper(
            "Usability of a brain-computer interface",
            "We measured mental workload and user experience of a P300 BCI."
        ), TOPICS)
        self.assertIn("bci-psychology", result["topics"])

    def test_generative_ai_creativity(self):
        result = m.classify(paper(
            "Generative AI for design ideation",
            "Designers used text-to-image models to support creative idea generation."
        ), TOPICS)
        self.assertIn("human-ai-creativity", result["topics"])

    def test_human_ai_behavior(self):
        result = m.classify(paper(
            "Trust in AI recommendations",
            "People delegated decisions to an algorithm and reported reliance and trust."
        ), TOPICS)
        self.assertIn("human-ai-behavior", result["topics"])

    def test_paper_can_belong_to_multiple_topics(self):
        result = m.classify(paper(
            "Human-AI collaboration in creative writing classrooms",
            "Students co-wrote stories with a generative AI chatbot to support creative ideation."
        ), TOPICS)
        self.assertTrue({"human-ai-education", "human-ai-creativity"} <= set(result["topics"]))

    def test_venue_groups_by_host_and_source(self):
        row = {"primary_location": {"source": {
            "id": "https://openalex.org/S4363607743",
            "display_name": "CHI",
            "issn": ["0000-0000"],
            "host_organization": "https://openalex.org/P4310319798",
        }}}
        self.assertIn("acm", m.venue_groups_for(row, VENUES))
        ieee = {"primary_location": {"source": {
            "id": "https://openalex.org/S1",
            "display_name": "IEEE Trans",
            "issn": [],
            "host_organization": "https://openalex.org/P4310319808",
        }}}
        self.assertIn("ieee", m.venue_groups_for(ieee, VENUES))

    def test_chunk_windows_splits_into_week_chunks(self):
        chunks = m.chunk_windows([("2026-01-15", "2026-01-31")])
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0], ("2026-01-15", "2026-01-21"))
        self.assertEqual(chunks[-1], ("2026-01-29", "2026-01-31"))

    def test_collection_plan_first_run_is_full(self):
        plan = m.collection_plan(dt.date(2026, 10, 25), {}, CONFIG)
        self.assertEqual(plan["mode"], "initial-full")
        self.assertEqual(plan["publication_windows"], [(CONFIG["coverage_start"], "2026-10-25")])

    def test_collection_plan_incremental_after_first_run(self):
        old = {"updated_at": "2026-10-24T12:00:00+00:00", "weekly_review_through": None}
        plan = m.collection_plan(dt.date(2026, 10, 25), old, CONFIG)
        self.assertEqual(plan["mode"], "daily-incremental")
        self.assertTrue(plan["publication_windows"][0][0] >= "2026-10-23")

    def test_normalize_skips_future_and_non_article_types(self):
        future = {
            "id": "https://openalex.org/W1", "title": "Future paper",
            "publication_date": "2027-01-01", "type": "article",
            "doi": "https://doi.org/10.1/X", "primary_location": {"source": None}, "authorships": [],
        }
        self.assertIsNone(m.normalize(future, "2026-10-25", set(), VENUES))
        book = {
            "id": "https://openalex.org/W2", "title": "A book",
            "publication_date": "2026-05-01", "type": "book",
            "doi": "https://doi.org/10.1/Y", "primary_location": {"source": None}, "authorships": [],
        }
        self.assertIsNone(m.normalize(book, "2026-10-25", set(), VENUES))

    def test_build_dataset_deduplicates_doi_across_result_sets(self):
        row = {
            "id": "https://openalex.org/W9", "title": "ChatGPT supports learners",
            "publication_date": "2026-10-05", "type": "article",
            "doi": "https://doi.org/10.1/DUP", "primary_location": {"source": None},
            "authorships": [], "abstract_inverted_index": {
                "Students": [0], "used": [1], "a": [2], "large": [3], "language": [4],
                "model": [5], "for": [6], "learning": [7], "in": [8], "the": [9], "classroom": [10],
            },
        }
        dataset = m.build_dataset({}, [[row], [row]], CONFIG, "2026-10-25", "2026-10-25T02:00:00+00:00")
        self.assertEqual(len(dataset["papers"]), 1)
        self.assertIn("human-ai-education", dataset["papers"][0]["topics"])

    def test_archive_is_retained_when_new_run_is_empty(self):
        row = {
            "id": "https://openalex.org/W10", "title": "A generative AI design study",
            "publication_date": "2026-10-06", "type": "article",
            "doi": "https://doi.org/10.1/KEEP", "primary_location": {"source": None},
            "authorships": [], "abstract_inverted_index": {
                "Designers": [0], "used": [1], "generative": [2], "ai": [3], "for": [4], "creative": [5], "ideation": [6],
            },
        }
        first = m.build_dataset({}, [[row]], CONFIG, "2026-10-24", "2026-10-24T02:00:00+00:00")
        second = m.build_dataset(first, [[]], CONFIG, "2026-10-25", "2026-10-25T02:00:00+00:00")
        self.assertEqual(len(second["papers"]), 1)


if __name__ == "__main__":
    unittest.main()



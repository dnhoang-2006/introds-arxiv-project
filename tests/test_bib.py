from pathlib import Path
from src.parser.bib import read_bib_file

SAMPLE_BIB = """
@article{vaswani2017attention,
  title = {{Attention} Is All You Need},
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki},
  journal = {Advances in Neural Information Processing Systems},
  year = {2017},
  doi = {10.5555/3295222},
  url = {https://arxiv.org/abs/1706.03762}
}

@book{goodfellow2016deep,
  title = {Deep Learning},
  author = {Ian Goodfellow and Yoshua Bengio},
  year = 2016
}
"""

def test_read_bib_file(tmp_path: Path):
    bib_file = tmp_path / "refs.bib"
    bib_file.write_text(SAMPLE_BIB, encoding="utf-8")

    entries = read_bib_file(bib_file)
    assert len(entries) == 2

    # Kiểm tra entry 1
    e1 = entries[0]
    assert e1["citation_key"] == "vaswani2017attention"
    assert e1["entry_type"] == "article"
    assert e1["title"] == "Attention Is All You Need"
    assert e1["authors"] == ["Vaswani, Ashish", "Shazeer, Noam", "Parmar, Niki"]
    assert e1["year"] == 2017
    assert e1["doi"] == "10.5555/3295222"
    assert e1["journal"] == "Advances in Neural Information Processing Systems"
    assert e1["url"] == "https://arxiv.org/abs/1706.03762"

    # Kiểm tra entry 2 (khuyết trường)
    e2 = entries[1]
    assert e2["citation_key"] == "goodfellow2016deep"
    assert e2["year"] == 2016
    assert e2["doi"] is None
    assert e2["url"] is None
#!/usr/bin/env python3
"""
Swarm-Synthesized Live Engrams.
Enables multiple A.I.M. agents to contribute knowledge fragments
to a shared pool with deduplication and trust scoring.
"""
import hashlib
from datetime import datetime, timezone

DEFAULT_TRUST_SCORE = 0.5


def create_fragment_contribution(content, source_agent, domain):
    """Create a well-formed fragment contribution for swarm exchange."""
    return {
        "content": content,
        "source_agent": source_agent,
        "domain": domain,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
    }


def deduplicate_fragments(fragments):
    """Remove duplicate fragments based on content hash."""
    seen = set()
    unique = []
    for frag in fragments:
        h = frag.get("content_hash")
        if h not in seen:
            seen.add(h)
            unique.append(frag)
    return unique


def score_fragment_trust(source_agent, known_agents):
    """Return trust score for a source agent. Unknown agents get DEFAULT_TRUST_SCORE."""
    return known_agents.get(source_agent, DEFAULT_TRUST_SCORE)


def merge_contributions(batches):
    """Merge fragment batches from multiple agents, deduplicating across all."""
    all_frags = []
    for batch in batches:
        all_frags.extend(batch)
    return deduplicate_fragments(all_frags)

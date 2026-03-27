import csv
from pathlib import Path
from typing import Dict, List, Tuple

class Alphabet:
    def __init__(self, segments: List[str], matrix: Dict[str, Dict[str, str]]):
        """
        matrix: A dictionary mapping segment -> {feature_name: value}
        e.g., {'A': {'F1': '+', 'F2': '+', 'F3': '+'}}
        """
        self.segments = segments
        self.matrix = matrix

    @classmethod
    def from_file(cls, filepath: Path) -> 'Alphabet':
        """Loads an Alphabet from a CSV or TSV file."""
        delimiter = '\t' if filepath.suffix.lower() == '.tsv' else ','
        
        with filepath.open('r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)
            
        if not rows:
            raise ValueError(f"Alphabet file {filepath} is empty.")
            
        # First row is the header: [0] is empty, [1:] are the segment characters
        segments = [s.strip() for s in rows[0][1:] if s.strip()]
        matrix = {seg: {} for seg in segments}
        
        # Parse the feature rows
        for row in rows[1:]:
            if not row or not row[0].strip():
                continue
            
            feature_name = row[0].strip()
            feature_values = row[1:]
            
            for seg, val in zip(segments, feature_values):
                matrix[seg][feature_name] = val.strip()
                
        return cls(segments, matrix)

def load_tests(filepath: Path) -> List[Tuple[str, str]]:
    """Loads input/output string pairs from a TSV or CSV."""
    delimiter = '\t' if filepath.suffix.lower() == '.tsv' else ','
    tests = []
    
    with filepath.open('r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=delimiter)
        # Skip header if it exists (e.g., Input\tOutput)
        header = next(reader, None)
        
        for row in reader:
            if len(row) >= 2:
                tests.append((row[0].strip(), row[1].strip()))
                
    return tests
# =============================================================================
# THINKING DISPLAY - Show LLM thinking steps in terminal
# =============================================================================

import re
from typing import List, Dict, Any, Optional


class ThinkingDisplay:
    """
    Display LLM thinking steps and summaries in the terminal.
    Parses LLM response to extract thinking blocks and display them alongside tool output.
    """
    
    def __init__(self):
        self.display_enabled = True
        self.thinking_prefix = "[LLM Thinking]"
        self.thinking_suffix = "[/LLM Thinking]"
        
    def enable(self):
        """Enable thinking display"""
        self.display_enabled = True
    
    def disable(self):
        """Disable thinking display"""
        self.display_enabled = False
    
    def parse_thinking_from_response(self, response: str) -> List[Dict]:
        """
        Parse LLM response to extract thinking steps.

        Looks for patterns like:
        - <<thinking>>...[/<<thinking>>]
        - [[thinking]]...[[/thinking]]
        - <thinking>...</thinking>
        - [THOUGHTS]...[/THOUGHTS]

        Returns list of thinking steps with their type (thought, summary, plan)
        """
        thinking_blocks = []

        # Pattern 1: <<thinking>> ... [/<<thinking>>]
        pattern1 = r'<<thinking>>\s*(.*?)\s*\[/<<thinking>>]'
        # Pattern 2: [[thinking]] ... [[/thinking]]
        pattern2 = r'\[\[thinking\]\]\s*(.*?)\s*\[\[\/thinking\]\]'
        # Pattern 3: <thinking>...</thinking>
        pattern3 = r'<thinking>\s*(.*?)\s*</thinking>'
        # Pattern 4: [THOUGHTS]...[/THOUGHTS]
        pattern4 = r'\[THOUGHTS\]\s*(.*?)\s*\[/THOUGHTS\]'

        # Extract all thinking blocks
        for pattern in [pattern1, pattern2, pattern3, pattern4]:
            matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
            for match in matches:
                # Clean up the thinking content
                clean_content = self._clean_thinking_content(match)

                # Determine thinking type
                thinking_type = self._determine_thinking_type(clean_content)

                # Extract summary if present
                summary = self._extract_summary(clean_content)

                thinking_blocks.append({
                    "content": clean_content.strip(),
                    "type": thinking_type,
                    "summary": summary,
                    "word_count": len(clean_content.split())
                })

        return thinking_blocks
    
    def _clean_thinking_content(self, content: str) -> str:
        """
        Clean thinking content by removing tool tags, code blocks, etc.
        """
        # Remove [TOOL] ... [/TOOL] blocks
        content = re.sub(r'\[TOOL\][\s\S]*?[/TOOL]', '', content, flags=re.IGNORECASE)
        # Remove ``` code blocks (keep minimal)
        content = re.sub(r'```(?:\w+)?\s*\n(?:.*?)\n```', '', content, flags=re.DOTALL)
        # Remove markdown formatting
        content = re.sub(r'[*_`#]', '', content)
        # Clean up whitespace
        content = ' '.join(content.split())
        return content
    
    def _determine_thinking_type(self, content: str) -> str:
        """
        Determine the type of thinking based on content.
        """
        content_lower = content.lower()
        
        if 'summary' in content_lower or 'done' in content_lower or 'complete' in content_lower:
            return "summary"
        elif 'tool' in content_lower or 'action' in content_lower:
            return "plan"
        else:
            return "thought"
    
    def _extract_summary(self, content: str) -> str:
        """
        Extract summary section if present.
        """
        summary_patterns = [
            r'\[summary\](.*?)\[\/summary\]',
            r'SUMMARY:\s*(.+?)(?=\n\n|\n|$)',
            r'=== SUMMARY ===\s*(.+?)\s*===',
        ]
        
        for pattern in summary_patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                # Clean up the summary
                summary = self._clean_thinking_content(match.group(1))
                return summary.strip()
        
        return ""
    
    def display_thinking(self, thinking_blocks: List[Dict], full_response: str = "") -> None:
        """
        Display thinking blocks in the terminal.
        
        Args:
            thinking_blocks: List of thinking block dictionaries
            full_response: The full LLM response (for reference)
        """
        if not self.display_enabled:
            return
        
        if not thinking_blocks:
            return
        
        print("\n" + "=" * 60)
        print(f"{self.thinking_prefix} ({len(thinking_blocks)} steps)")
        print("=" * 60)
        
        # Check if there's a summary section
        summary_block = next((b for b in thinking_blocks if b["type"] == "summary"), None)
        
        if summary_block:
            print(f"\n>>> SUMMARY ({summary_block['word_count']} words):\n")
            print(f"{summary_block['content']}\n")
            
            # After summary, show the detailed thinking steps
            other_blocks = [b for b in thinking_blocks if b["type"] != "summary"]
            for i, block in enumerate(other_blocks, 1):
                print(f"\n--- Thinking Step {i} ({block['type']}): {block['word_count']} words ---")
                print(block['content'])
        else:
            # No summary - show all thinking blocks
            for i, block in enumerate(thinking_blocks, 1):
                prefix = ">>> " if block['type'] == "summary" else f">>> Step {i} ({block['type']})"
                print(f"{prefix} ({block['word_count']} words):\n")
                print(block['content'])
        
        print("=" * 60 + "\n")
    
    def display_step_by_step(self, thinking_blocks: List[Dict], response: str, stream: bool = False) -> None:
        """
        Display thinking blocks step by step (for streaming responses).
        
        Args:
            thinking_blocks: List of thinking block dictionaries
            response: The full LLM response
            stream: If True, display as response is being generated
        """
        if not self.display_enabled:
            return
        
        if not thinking_blocks:
            return
        
        print(f"\n{self.thinking_prefix}")
        
        for i, block in enumerate(thinking_blocks, 1):
            # For streaming, show partial output
            if stream:
                print(block['content'][:200] + "...", end="", flush=True)
            else:
                print(f"\n>>> Step {i} ({block['type']}):\n{block['content']}")
            
            print(self.thinking_suffix)
    
    def show_response_summary(self, response: str) -> str:
        """
        Extract and return a brief summary of the LLM response.
        
        Args:
            response: The full LLM response
            
        Returns:
            Brief summary string
        """
        # Clean the response
        clean_response = self._clean_thinking_content(response)
        
        # Look for summary markers
        summary_match = re.search(
            r'(?:\[summary\](.*?)\[\/summary\]|SUMMARY:\s*(.+?)(?=\n\n|\n|$=== SUMMARY ===)',
            response,
            re.DOTALL | re.IGNORECASE
        )
        
        if summary_match:
            summary = self._clean_thinking_content(summary_match.group(1))
            return summary.strip()
        
        # If no summary, return first paragraph
        paragraphs = clean_response.split('\n\n')
        if paragraphs:
            first_para = paragraphs[0]
            # Limit length
            if len(first_para) > 500:
                return first_para[:500] + "..."
            return first_para
        
        return response[:300] + "..." if len(response) > 300 else response


# Global thinking display instance
thinking_display = ThinkingDisplay()

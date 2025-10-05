import os
import time
import argparse
import pandas as pd
import importlib.util
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai
import traceback

load_dotenv()

MODEL_NAME = 'gemini-2.5-pro'
MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """
You are an expert AI coding agent. Your sole purpose is to write a standalone, production-quality Python parser for a given bank statement PDF.

**Your Goal:**
- Write a single Python file: `custom_parsers/{bank_name}_parser.py`.
- This file must contain one function: `parse(pdf_path: str) -> pandas.DataFrame`.
- The DataFrame returned by your `parse` function MUST EXACTLY MATCH the schema and data of the provided sample CSV.

**Parser Requirements:**
1.  **Process All Pages:** Your parser **must iterate through all pages** of the PDF to extract every single transaction. This is critical for correctness.
2.  **Robust Data Handling:** Your generated code must be resilient.
    - Always convert column headers to strings before processing them (e.g., `str(col).strip()`).
    - Meticulously clean data: strip whitespace, remove currency symbols, ensure consistent date formats.
3.  **Crucial Bank Statement Logic:** A single transaction row can have a value in the 'Debit' column OR the 'Credit' column, but **never both**. If a value exists for one, the other must be null or an empty string.
4.  **Dependency-Light:** Do not use libraries outside the standard library, `pandas`, `pdfplumber`, and `camelot-py`.
5.  **Error Handling:** If the PDF is unparsable, return an empty DataFrame with the correct column names from the CSV schema.
6.  **No Placeholders:** The code must be complete and functional. Your response should contain ONLY the Python code for the parser, without any surrounding text or markdown.
"""

def analyze_data(pdf_path: str, csv_path: str) -> tuple[str, str]:
    """Extracts text from PDF and gets schema info from CSV for the prompt."""
    try:
        import pdfplumber
        # Extract text from the first two pages to give the AI context
        with pdfplumber.open(pdf_path) as pdf:
            pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages[:2])
    except Exception as e:
        pdf_text = f"[Could not extract text from PDF: {e}]"

    df = pd.read_csv(csv_path, nrows=5)
    csv_preview = f"""
    First 5 rows of the target CSV:
    {df.to_string()}

    Column names and data types of the target CSV:
    {df.info()}
    """
    return pdf_text, csv_preview


def generate_parser(model, bank_name: str, pdf_text: str, csv_preview: str) -> Path:
    """Generates the initial parser code using the Gemini model."""
    prompt = f"""
    {SYSTEM_PROMPT}
    **Bank Name:** {bank_name}
    **Partial Text from PDF Statement:**
    ```{pdf_text or '[No extractable text detected.]'}```
    **Target CSV Schema and Data Preview:**
    ```{csv_preview}```
    Now, write the complete, final Python code for the parser file `custom_parsers/{bank_name}_parser.py`.
    """

    print("Generating initial parser code...")
    response = model.generate_content(prompt)
    code = response.text

    # Clean up the response to extract only the code
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0].strip()

    parser_dir = Path("custom_parsers")
    parser_dir.mkdir(exist_ok=True)
    parser_path = parser_dir / f"{bank_name}_parser.py"
    parser_path.write_text(code, encoding="utf-8")

    print(f"✅ Parser written to {parser_path}")
    return parser_path

def run_parser_test(parser_path: Path, pdf_path: str, csv_path: str) -> tuple[bool, str]:
    """Tests the generated parser and returns detailed feedback on failure."""
    if not parser_path.exists():
        return False, "Parser file does not exist."

    try:
        spec = importlib.util.spec_from_file_location("parser_module", parser_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Load expected_df and clean it
        expected_df = pd.read_csv(csv_path, dtype=str)
        expected_df = expected_df.fillna('').apply(lambda x: x.str.strip())

        # Load result_df from the parser
        result_df = module.parse(pdf_path)

        if result_df is None:
            raise TypeError("The parse() function returned None, but a DataFrame was expected.")
        if not isinstance(result_df, pd.DataFrame):
             raise TypeError(f"The parse() function returned a {type(result_df)}, but a DataFrame was expected.")

        # Force all columns to string type for a fair comparison
        result_df = result_df.astype(str)
        
        # THIS IS THE KEY FIX: Replace all common null variations with a true empty string
        for col in result_df.columns:
             result_df[col] = result_df[col].str.replace(r'^(nan|<NA>|None)$', '', regex=True)

        result_df = result_df.fillna('').apply(lambda x: x.str.strip())


        # The core of the test: use pandas' testing utility
        pd.testing.assert_frame_equal(expected_df, result_df, check_like=True)
        return True, "✅ Test passed! DataFrames are identical."

    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e).replace('\n', '\n  ')
        feedback = f"""
        The parser failed with a '{error_type}' error.
        **Error Details:**
        {error_message}
        **Traceback:**
        {traceback.format_exc()}
        """
        return False, feedback
def fix_parser(model, parser_path: Path, feedback: str) -> Path:
    """Attempts to fix the parser code based on the failure feedback."""
    print("🔧 Parser failed. Attempting to self-correct...")
    original_code = parser_path.read_text(encoding="utf-8")

    prompt = f"""
    You are an AI code-fixing agent. The following Python parser failed its test.
    Read the error feedback and the original code, then provide a corrected version.

    **Failure Feedback:**
    ```
    {feedback}
    ```

    **Hint:** If the error is a `DataFrame shape mismatch`, it means your code did not extract all the rows from the PDF. Your logic MUST iterate through all pages of the document. If the error is about a `Debit` or `Credit` column, remember that a transaction can only be one or the other.

    **Original Code:**
    ```python
    {original_code}
    ```

    Your task is to rewrite the entire Python script to fix the bug.
    Your response must contain ONLY the corrected Python code, enclosed in ```python ... ```.
    """

    response = model.generate_content(prompt)
    new_code = response.text

    if "```python" in new_code:
        new_code = new_code.split("```python")[1].split("```")[0].strip()

    parser_path.write_text(new_code, encoding="utf-8")
    print(f"🔩 Parser updated at {parser_path}")
    return parser_path


def main():
    parser = argparse.ArgumentParser(description="An AI agent that writes PDF parsers.")
    parser.add_argument("--target", required=True, help="The bank name (e.g., 'icici')")
    args = parser.parse_args()
    bank_name = args.target.lower()

    pdf_path = Path(f"data/{bank_name}/{bank_name}_sample.pdf")
    csv_path = Path(f"data/{bank_name}/{bank_name}_sample.csv")

    if not all([pdf_path.exists(), csv_path.exists()]):
        print(f" Error: Missing PDF or CSV for '{bank_name}'. Ensure these files exist:\n- {pdf_path}\n- {csv_path}")
        return

    try:
        # Configure the Gemini API client
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set.")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(MODEL_NAME)
    except (ValueError, ImportError) as e:
        print(f" Error: {e}")
        return

    print(f" Starting agent for bank: {bank_name.upper()}")
    pdf_text, csv_preview = analyze_data(pdf_path, csv_path)
    parser_path = generate_parser(model, bank_name, pdf_text, csv_preview)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n Running Test Attempt {attempt}/{MAX_ATTEMPTS}...")
        success, feedback = run_parser_test(parser_path, str(pdf_path), str(csv_path))

        if success:
            print(f"\n🎉 {feedback}")
            print("Agent completed successfully.")
            return

        print(f" Test Failed. Reason:\n{feedback}")
        if attempt < MAX_ATTEMPTS:
            time.sleep(2) # A small delay can be helpful
            parser_path = fix_parser(model, parser_path, feedback)
        else:
            print(f"\n All {MAX_ATTEMPTS} attempts failed. Manual review required.")
            break

if __name__ == "__main__":
    main()
"""Unified entry point. No workflow starts until the user runs this file."""
from financial_workbook.app import main

if __name__=='__main__':
    raise SystemExit(main())

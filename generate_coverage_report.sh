#!/bin/bash
# Script to generate and display test coverage report
# Usage: bash generate_coverage_report.sh

set -e

echo "🧪 Linkplay - Test Coverage Report Generator"
echo "=========================================================="
echo ""

# Check if dependencies are installed
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest not found. Installing test dependencies..."
    pip install -r requirements-test.txt
fi

echo "📊 Running tests with coverage analysis..."
echo ""

# Run tests with coverage
pytest tests/ \
  --cov=custom_components.linkplay \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-report=json \
  --cov-report=xml \
  -v

echo ""
echo "✅ Test execution complete!"
echo ""
echo "📈 Coverage Report Formats Generated:"
echo ""
echo "1. Terminal (above) ✓"
echo "   Shows coverage percentage and uncovered lines"
echo ""
echo "2. HTML Report"
echo "   Location: htmlcov/index.html"
echo "   Open with: open htmlcov/index.html"
echo ""
echo "3. JSON Report"
echo "   Location: coverage.json"
echo "   Use for: CI/CD integration"
echo ""
echo "4. XML Report"
echo "   Location: coverage.xml"
echo "   Use for: SonarQube, Codacy integration"
echo ""
echo "📊 Quick Statistics:"
echo ""

# Extract coverage percentage from JSON if available
if [ -f "coverage.json" ]; then
    python3 << EOF
import json
with open('coverage.json') as f:
    data = json.load(f)
    coverage = data['totals']['percent_covered']
    statements = data['totals']['num_statements']
    missing = data['totals']['missing_lines']
    executed = statements - missing
    print(f"   Total Lines:        {statements}")
    print(f"   Lines Executed:     {executed}")
    print(f"   Lines Missing:      {missing}")
    print(f"   Coverage:           {coverage:.1f}%")
EOF
fi

echo ""
echo "✨ Ready for Home Assistant core submission!"
echo ""


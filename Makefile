install:
	pip install -r requirements.txt

lint:
	flake8 . --max-line-length=120 --exclude=dbt_pipeline/target,dbt_pipeline/dbt_packages,.venv

test:
	pytest tests/ -v --cov=. --cov-report=term-missing

dagster:
	dagster dev

streamlit:
	streamlit run streamlit_app/app.py

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete

default:
	$(warning Choose extract, init, or update!)

extract:
	pybabel extract -F lykan/babel.cfg -o lykan/translations/messages.pot lykan

update: extract
	pybabel update -i lykan/translations/messages.pot -d lykan/translations

init:
	echo Initing ${LANG} ...
	pybabel init -i lykan/translations/messages.pot -d lykan/translations -l ${LANG}
	mkdir -p lykan/translations/${LANG}/voice

speechload: update
	python -m lykan.speechloader

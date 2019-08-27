Lykan
=====

Lykan is an implementation of the popular social game called "Werewolves".

See AUTHORS for a list of authors holding the copyright of this software.

License
-------

AGPL v3 or later.

Installation
------------

 1. Install Python 3.7, virtualenv, and pip::

      sudo apt install python3-pip virtualenv python3-virtualenv python3-dev

 2. Create a virtual environment using Python 3.7::

      virtualenv -p python3 env

 3. Active the environment::

      . env/bin/activate

 4. Install the dependencies into the virtual environment::

      pip install -r requirements.txt

 5. Run the game::

      python -m lykan.main 8080

 6. Navigate to http://localhost:8080/


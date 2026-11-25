<?php

Route::get('/', fn () => view('welcome', ['name' => env('APP_NAME')]));

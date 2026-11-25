<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Post extends Model
{
    // $guarded = [] in a comment must not be reported
    protected $guarded = [];
}

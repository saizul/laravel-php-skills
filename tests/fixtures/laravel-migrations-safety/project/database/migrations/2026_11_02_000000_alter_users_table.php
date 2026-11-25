<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::table('users', function (Blueprint $table) {
            // $table->dropColumn('ignored_in_comment');
            $table->dropColumn('legacy_flag');
            $table->renameColumn('name', 'full_name');
            $table->string('email', 320)->change();
            $table->string('timezone');
            $table->string('locale')->default('en');
            $table->boolean('beta')->nullable();
            $table->string('username')->unique();
            $table->index('created_at');
            $table->foreignId('team_id')->constrained();
        });
    }
};
